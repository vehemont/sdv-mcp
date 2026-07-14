"""sdv_wiki.py - Read-only client for the Stardew Valley Wiki MediaWiki API.

Live retrieval (not a vector store) used to VERIFY game facts and pull context
the save parser can't provide - prices, seasons, drop locations, event schedules.
Grounding answers in retrieved wiki text is the anti-hallucination layer.

Read-only: only performs GET queries against the public API. Responses are cached
in-process by (endpoint, params) to be gentle on the wiki.

Docs/etiquette: sends a descriptive User-Agent and maxlag; content is CC BY-NC-SA.
"""
from __future__ import annotations
import json, re, time, urllib.parse, urllib.request

# NOTE: this wiki's MediaWiki REST API (rest.php/v1/...) returns empty responses,
# so we use the Action API (api.php), which is fully functional and more flexible.
API = "https://stardewvalleywiki.com/mediawiki/api.php"
UA = "sdv-save-inspector/1.0 (personal wiki-verification tool; contact: local user)"
_CACHE = {}
_TTL = 3600          # seconds
_MIN_INTERVAL = 0.5  # simple rate limit between live calls
_last_call = [0.0]

def _get(params):
    params = {**params, "format": "json", "formatversion": "2", "maxlag": "5"}
    key = urllib.parse.urlencode(sorted(params.items()))
    now = time.time()
    hit = _CACHE.get(key)
    if hit and now - hit[0] < _TTL:
        return hit[1]
    # polite rate limit
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
def search(query, limit=6):
    """Full-text search. Returns [{title, snippet, pageid}]."""
    d = _get({"action": "query", "list": "search", "srsearch": query, "srlimit": str(limit)})
    out = []
    for r in d.get("query", {}).get("search", []):
        snip = re.sub(r"<[^>]+>", "", r.get("snippet", ""))
        out.append({"title": r["title"], "pageid": r["pageid"], "snippet": snip})
    return {"query": query, "results": out}

def page(title, section=None, raw=False, max_chars=6000):
    """Fetch a page as cleaned plain text (or raw wikitext). If section is given
    (a heading title), return just that section. Follows redirects."""
    d = _get({"action": "parse", "page": title, "prop": "wikitext", "redirects": "1"})
    if "error" in d:
        return {"title": title, "error": d["error"].get("info", "not found")}
    p = d["parse"]
    wt = p["wikitext"]
    if section:
        wt = _extract_section(wt, section)
        if wt is None:
            return {"title": p["title"], "error": f"section '{section}' not found",
                    "sections": _list_sections(p["wikitext"])}
    text = wt if raw else clean_wikitext(wt)
    truncated = len(text) > max_chars
    return {"title": p["title"], "pageid": p["pageid"],
            "sections": _list_sections(p["wikitext"]),
            "content": text[:max_chars], "truncated": truncated,
            "url": "https://stardewvalleywiki.com/" + p["title"].replace(" ", "_"),
            "source": "Stardew Valley Wiki (CC BY-NC-SA)"}

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
