"""sdv_wiki.py - Read-only client for the Stardew Valley Wiki MediaWiki API.

Live retrieval (not a vector store) used to VERIFY game facts and pull context
the save parser can't provide - prices, seasons, drop locations, event schedules.
Grounding answers in retrieved wiki text is the anti-hallucination layer.

Read-only: only performs GET queries against the public API. Responses are cached
in-process by (endpoint, params) to be gentle on the wiki.

Docs/etiquette: sends a descriptive User-Agent and maxlag; content is CC BY-NC-SA.
"""
from __future__ import annotations
import json, re, threading, time, urllib.parse, urllib.request

# NOTE: this wiki runs MediaWiki 1.35 (no CirrusSearch, no TextExtracts). The REST API
# (rest.php/v1/...) returns empty responses, so we use the Action API (api.php). Two facts
# drive the design here:
#   * list=search is the basic DB search: it ANDs every term and has NO fuzzy ranking or
#     "did you mean" (srinfo=suggestion is empty), so multi-word/natural-language queries
#     usually return 0 hits. For TITLE resolution we fall back to OpenSearch (prefix match).
#   * TextExtracts (prop=extracts) is not installed, so summaries must be built by fetching
#     wikitext (action=parse&prop=wikitext) and cleaning it ourselves - see clean_wikitext.
# (Cargo is installed but UNUSED for game data: item/gift/recipe facts live in infobox
#  template params + Lua modules, not Cargo tables, so action=cargoquery is a dead end here.)
API = "https://stardewvalleywiki.com/mediawiki/api.php"
UA = "sdv-save-inspector/1.0 (personal wiki-verification tool; contact: local user)"
_CACHE = {}
_TTL = 3600          # seconds
_MIN_INTERVAL = 0.5  # simple rate limit between live calls
_last_call = [0.0]
_LOCK = threading.Lock()

def _get(params):
    params = {**params, "format": "json", "formatversion": "2", "maxlag": "5"}
    key = urllib.parse.urlencode(sorted(params.items()))
    now = time.time()
    hit = _CACHE.get(key)
    if hit and now - hit[0] < _TTL:
        return hit[1]
    # polite rate limit (serialized so concurrent callers don't hammer the wiki)
    with _LOCK:
        now = time.time()
        hit = _CACHE.get(key)  # re-check: another thread may have just cached it
        if hit and now - hit[0] < _TTL:
            return hit[1]
        wait = _MIN_INTERVAL - (now - _last_call[0])
        if wait > 0:
            time.sleep(wait)
        url = API + "?" + key
        req = urllib.request.Request(url, headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=20) as r:
            data = json.loads(r.read().decode("utf-8"))
        _last_call[0] = time.time()
        _CACHE[key] = (_last_call[0], data)
        return data

# ---------------- wikitext cleanup ----------------------------------------
def _strip_links(t):
    # [[target|label]] -> label ; [[target]] -> target
    t = re.sub(r"\[\[([^\]|]+)\|([^\]]+)\]\]", r"\2", t)
    t = re.sub(r"\[\[([^\]]+)\]\]", r"\1", t)
    return t

def _expand_name_templates(t):
    # {{Name|Item|qty}} -> "qty Item" ; {{Name|Item}} -> "Item"
    def repl(m):
        parts = [p.strip() for p in m.group(1).split("|")]
        if len(parts) >= 2 and parts[1]:
            return f"{parts[1]} {parts[0]}"
        return parts[0]
    t = re.sub(r"\{\{Name\|([^{}]+)\}\}", repl, t)
    # {{Price|100|Calico}} -> "100 Calico" ; {{Tprice|200}} -> "200"
    t = re.sub(r"\{\{T?[Pp]rice\|([^{}]+)\}\}", lambda m: " ".join(x.strip() for x in m.group(1).split("|")), t)
    # {{Season|Summer}} -> "Summer"
    t = re.sub(r"\{\{Season\|([^{}|]+)[^{}]*\}\}", r"\1", t)
    return t

def clean_wikitext(t, keep_tables=True):
    """Turn wikitext into readable plain text: expand common templates, drop
    links/refs/HTML, optionally flatten tables to lines."""
    t = _expand_name_templates(t)
    t = _strip_links(t)
    t = re.sub(r"<ref[^>]*?/>", "", t)
    t = re.sub(r"<ref[^>]*?>.*?</ref>", "", t, flags=re.S)
    t = re.sub(r"<!--.*?-->", "", t, flags=re.S)
    t = re.sub(r"'''?", "", t)                    # bold/italic
    t = re.sub(r"\{\{Quote\|([^{}]*)\|[^{}]*\}\}", r'"\1"', t)   # {{Quote|text|src}}
    if keep_tables:
        t = t.replace("{|", "").replace("|}", "")
        t = re.sub(r"\|-\s*", "\n", t)
        t = re.sub(r"^[!|]\s*", "", t, flags=re.M)
        t = t.replace("||", " | ").replace("!!", " | ")
    t = re.sub(r"\{\{[^{}]*\}\}", "", t)         # drop leftover simple templates
    t = re.sub(r"<[^>]+>", "", t)                 # residual HTML tags
    t = re.sub(r"[ \t]{2,}", " ", t)
    t = re.sub(r"\n{3,}", "\n\n", t)
    return t.strip()

# ---------------- public API ----------------------------------------------
# words that add noise to a wiki title search (questions/filler, not topic nouns)
_SEARCH_STOPWORDS = {
    'a','an','the','of','for','to','in','on','at','is','are','do','does','how','what',
    'where','which','who','when','why','can','i','you','my','much','many','cost','costs',
    'price','prices','priced','buy','buying','get','getting','obtain','sell','sells','and',
    'or','from','with','best','way','ways','shop','store',
}

def _keywords(query):
    """Topic nouns from a query: drop question/filler words and near-duplicate stems
    (so 'seed'/'seeds' collapse), preserving order - used only to SUGGEST a better query."""
    kept = []; seen = set()
    for w in re.findall(r"[A-Za-z0-9']+", query):
        if w.lower() in _SEARCH_STOPWORDS:
            continue
        stem = w.lower().rstrip('s')
        if stem in seen:
            continue
        seen.add(stem); kept.append(w)
    return kept

def opensearch(term, limit=6):
    """Title/prefix search via the MediaWiki OpenSearch protocol. Returns matching page
    TITLES. This wiki (MediaWiki 1.35, no CirrusSearch) has only a strict full-text search
    that requires every word to match; OpenSearch is prefix-based and the reliable way to
    resolve an item/NPC name to its exact page title. Returns [] on no match."""
    d = _get({"action": "opensearch", "search": term, "limit": str(limit),
              "redirects": "resolve", "namespace": "0"})
    # OpenSearch returns [term, [titles], [descriptions], [urls]] (fixed shape).
    try:
        return list(d[1])
    except (IndexError, TypeError, KeyError):
        return []

def _prefix_range_titles(prefix, limit=100):
    """Page titles starting with `prefix`, matched CASE-INSENSITIVELY. The wiki's allpages
    collation (apfrom..apto) is case-insensitive but breaks on multi-word ranges, so we
    fetch the alphabetical window for the FIRST word (first .. first+sentinel) and then
    filter to titles that actually start with the full (possibly multi-word) prefix. This
    handles 'void essence' -> Void Essence, 'puffer' -> Pufferfish regardless of casing."""
    if not prefix:
        return []
    first = prefix.split(" ")[0]
    d = _get({"action": "query", "list": "allpages", "apfrom": first,
              "apto": first + "\u00ff", "aplimit": str(limit), "apnamespace": "0"})
    low = prefix.lower()
    return [p["title"] for p in d.get("query", {}).get("allpages", [])
            if p["title"].lower().startswith(low)]

def _best_title(query_words, titles):
    """Pick the most relevant title from prefix matches: prefer one containing the most
    query words (so 'void essence' beats 'Void Chicken'), then the shortest (most specific)."""
    def score(t):
        tl = t.lower()
        overlap = sum(1 for w in query_words if w.lower().rstrip('s') in tl)
        return (overlap, -len(t))
    return max(titles, key=score) if titles else None

def resolve_title(query, limit=6):
    """Resolve any reasonable spelling of an item/NPC/page name to a canonical wiki page
    title. Returns {"title": <canonical or None>, "suggestions": [...], "via": <how>}.

    Weak-model friendly: handles lowercase, plurals, multiword phrases, and partial names.
    Strategy: build prefix candidates from the topic keywords (full phrase first, then
    fewer leading words), match each case-insensitively against allpages, and pick the hit
    containing the most query words. Falls back to OpenSearch. The caller does NOT need to
    pre-clean the query - pass whatever name the user gave ('bat wing', 'Large Goat Milk',
    'prismatic shard best way')."""
    kw = _keywords(query)
    if not kw:
        kw = [w for w in re.findall(r"[A-Za-z0-9']+", query) if w]
    if not kw:
        return {"title": None, "suggestions": [], "via": "empty query"}
    # candidate prefixes, most-specific first: full phrase, then drop the last word, etc.
    cands, seen = [], set()
    def add(words):
        v = " ".join(words)
        if v and v.lower() not in seen:
            seen.add(v.lower()); cands.append(words)
    add(kw)
    if kw[-1].lower().endswith("s"):                 # de-pluralize last word as an alt
        add(kw[:-1] + [kw[-1][:-1]])
    for n in range(len(kw) - 1, 0, -1):              # fewer leading keywords
        add(kw[:n])
    for words in cands:
        hits = _prefix_range_titles(" ".join(words), limit=50)
        if hits:
            best = _best_title(kw, hits)
            return {"title": best, "suggestions": hits[:limit], "via": f"prefix({' '.join(words)!r})"}
    for words in cands:
        hits = opensearch(" ".join(words), limit=limit)
        if hits:
            best = _best_title(kw, hits)
            return {"title": best, "suggestions": hits, "via": f"opensearch({' '.join(words)!r})"}
    return {"title": None, "suggestions": [], "via": "no match"}

def search(query, limit=6):
    """Full-text search for a page TITLE. Returns [{title, snippet, pageid}].

    This wiki's search requires every word to match (no fuzzy ranking), so search the topic
    noun in 1-3 words (e.g. 'Rhubarb Seeds'), not a natural-language question. If you already
    know the item/NPC name, skip search and call how_to_obtain/wiki_infobox/wiki_page. On no
    match, this falls back to OpenSearch title matching and returns candidate `suggestions`."""
    d = _get({"action": "query", "list": "search", "srsearch": query,
              "srlimit": str(limit), "srnamespace": "0"})
    out = []
    for r in d.get("query", {}).get("search", []):
        snip = re.sub(r"<[^>]+>", "", r.get("snippet", ""))
        out.append({"title": r["title"], "pageid": r["pageid"], "snippet": snip})
    resp = {"query": query, "results": out}
    if out:
        resp["next_step"] = (f"Open the right page directly: how_to_obtain(\"{out[0]['title']}\") "
                             f"or wiki_infobox(\"{out[0]['title']}\").")
        return resp
    # No full-text hit: resolve real page titles via the stronger cascade resolver
    # (allpages prefix + OpenSearch), which tolerates lowercase/plural/partial input.
    r = resolve_title(query)
    suggestions = r["suggestions"]
    resp["suggestions"] = suggestions
    if suggestions:
        resp["hint"] = (f"No full-text match (this wiki's search needs every word to match). "
                        f"Closest page titles: {suggestions}. Open the right one with "
                        f"how_to_obtain(title)/wiki_infobox(title)/wiki_page(title) - don't re-search.")
    else:
        resp["hint"] = ("No match. Search the item/NPC noun in 1-3 words (Capitalized, "
                        "singular), or call how_to_obtain(name)/wiki_infobox(name) directly.")
    return resp

def page(title, section=None, raw=False, max_chars=6000):
    """Fetch a page as cleaned plain text (or raw wikitext). If section is given
    (a heading title), return just that section. Follows redirects."""
    d = _get({"action": "parse", "page": title, "prop": "wikitext|sections", "redirects": "1"})
    if "error" in d:
        return {"title": title, "error": d["error"].get("info", "not found")}
    p = d["parse"]
    wt = p["wikitext"]
    sections = _toc(d)
    if section:
        wt = _extract_section(wt, section)
        if wt is None:
            return {"title": p["title"], "error": f"section '{section}' not found",
                    "sections": sections}
    text = wt if raw else clean_wikitext(wt)
    truncated = len(text) > max_chars
    return {"title": p["title"], "pageid": p["pageid"],
            "sections": sections,
            "content": text[:max_chars], "truncated": truncated,
            "url": "https://stardewvalleywiki.com/" + p["title"].replace(" ", "_"),
            "source": "Stardew Valley Wiki (CC BY-NC-SA)"}

def _toc(parse_response):
    """Ordered table-of-contents (heading lines) from an action=parse response that
    requested prop=sections. Cleaner than regexing wikitext (handles nested levels,
    template-injected headings)."""
    secs = parse_response.get("parse", {}).get("sections", [])
    out = []
    for s in secs:
        line = s.get("line", "").strip()
        if line and line not in out:
            out.append(line)
    return out

def _list_sections(wt):
    return re.findall(r"^==+\s*([^=]+?)\s*==+\s*$", wt, flags=re.M)

def _extract_section(wt, name):
    lines = wt.split("\n"); out = []; grab = False; level = None
    for ln in lines:
        m = re.match(r"^(=+)\s*(.+?)\s*=+\s*$", ln)
        if m:
            hl = len(m.group(1)); title = m.group(2)
            if grab and hl <= level:      # next same/higher heading ends section
                break
            if title.strip().lower() == name.strip().lower():
                grab = True; level = hl; continue
        if grab:
            out.append(ln)
    return "\n".join(out).strip() if grab else None

def summary(title, max_chars=700):
    """The lead section (everything before the first heading) as cleaned plain
    text. For an item page this is the 'how to obtain / what it's used for'
    overview - e.g. every acquisition method (drops, shop purchases, trades,
    gifting), which is what you want when planning how to get a quest item."""
    d = _get({"action": "parse", "page": title, "prop": "wikitext", "redirects": "1"})
    if "error" in d:
        return {"title": title, "error": d["error"].get("info", "not found")}
    p = d["parse"]; wt = p["wikitext"]
    lead = re.split(r"\n==", wt, 1)[0]                       # text before first section
    lead = re.sub(r"\{\{Infobox.*?\n\}\}", "", lead, flags=re.S)  # drop the infobox block
    text = clean_wikitext(lead)
    return {"title": p["title"], "summary": text[:max_chars],
            "truncated": len(text) > max_chars,
            "url": "https://stardewvalleywiki.com/" + p["title"].replace(" ", "_"),
            "source": "Stardew Valley Wiki (CC BY-NC-SA)"}

def infobox(title):
    """Parse the page's first infobox-style template into key/value fields
    (e.g. sell price, season, location) - the best surface for verification."""
    d = _get({"action": "parse", "page": title, "prop": "wikitext", "redirects": "1"})
    if "error" in d:
        return {"title": title, "error": d["error"].get("info", "not found")}
    p = d["parse"]; wt = p["wikitext"]
    m = re.search(r"\{\{Infobox([^\n]*)\n(.*?)\n\}\}", wt, flags=re.S)
    if not m:
        return {"title": p["title"], "fields": {}, "note": "no infobox template found"}
    fields = {}
    for line in m.group(2).split("\n|"):
        if "=" in line:
            k, v = line.split("=", 1)
            v = clean_wikitext(v.strip(), keep_tables=False)
            k = k.strip().lstrip("|").strip()
            if k and v:
                fields[k] = v
    return {"title": p["title"], "infobox_type": m.group(1).strip(),
            "fields": fields,
            "url": "https://stardewvalleywiki.com/" + p["title"].replace(" ", "_"),
            "source": "Stardew Valley Wiki (CC BY-NC-SA)"}

def category(name, limit=200):
    """All member pages of a wiki category, e.g. 'Spring fish' -> the 37 spring-fish pages.
    Accepts the name with or without the 'Category:' prefix. Category titles are
    case-sensitive after the first character on MediaWiki, so this retries common
    casings ('Summer Crops' -> 'Summer crops') and prefix-matches before giving up.
    Use this to answer 'all X in season Y' / 'every <type> of <category>' questions
    exhaustively instead of guessing individual pages."""
    raw = name.strip()
    if raw.lower().startswith("category:"):
        raw = raw.split(":", 1)[1]

    def members_of(title):
        d = _get({"action": "query", "list": "categorymembers", "cmtitle": title,
                  "cmlimit": str(limit), "cmtype": "page|subcat"})
        if "error" in d:
            return None, d["error"].get("info", "not found")
        return d.get("query", {}).get("categorymembers", []), None

    # Candidate casings, most-likely first: as-given, first-letter-upper/rest-lower,
    # full lowercase, Title Case. MediaWiki needs the first letter capitalized and is
    # case-sensitive after it, which is why 'Summer Crops' fails but 'Summer crops' works.
    # Dedup on the EXACT string (case matters to the API), not on .lower().
    cands, seen = [], set()
    def add(c):
        if c and c not in seen:
            seen.add(c); cands.append(c)
    add(raw)
    add(raw[:1].upper() + raw[1:].lower() if raw else raw)
    add(raw.lower())
    add(raw.title())

    members, resolved_cat, err = None, None, None
    for c in cands:
        title = "Category:" + c
        members, err = members_of(title)
        if members:
            resolved_cat = title
            break
    if not members:
        # Last resort: prefix-match within the category namespace (ns=14) for suggestions.
        rd = _get({"action": "query", "list": "allpages", "apprefix": raw,
                   "aplimit": "8", "apnamespace": "14"})
        suggestions = [p["title"] for p in rd.get("query", {}).get("allpages", [])]
        if not suggestions and raw:
            # try a first-letter-capitalized prefix too
            rd = _get({"action": "query", "list": "allpages",
                       "apprefix": raw[:1].upper() + raw[1:], "aplimit": "8",
                       "apnamespace": "14"})
            suggestions = [p["title"] for p in rd.get("query", {}).get("allpages", [])]
        return {"category": "Category:" + raw, "members": [], "suggestions": suggestions,
                "hint": "No members. Category titles are case-sensitive - did you mean: " +
                        (", ".join(suggestions) if suggestions else
                         f"none. Try wiki_search(\"{raw}\") to find the right category.")}

    pages = [m["title"] for m in members if m["ns"] == 0]
    subcats = [m["title"] for m in members if m["ns"] == 14]
    out = {"category": resolved_cat, "count": len(pages), "pages": pages,
           "source": "Stardew Valley Wiki (CC BY-NC-SA)"}
    if subcats:
        out["subcategories"] = subcats
    return out
