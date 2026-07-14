#!/usr/bin/env python3
"""Stardew Valley save inspector - read-only MCP server.

Exposes a Stardew save + the Stardew Wiki + a set of calculators to an MCP client
as structured, read-only data. The server NEVER writes to the save; it only
parses/queries and returns facts. Recommendations are left to the client/LLM.

Contract notes for the calling model:
- Every tool has a description (below) and an INPUT schema with per-parameter
  descriptions and enums for constrained choices.
- Calculator tools declare an OUTPUT schema (field names + types). Because MCP
  TypedDict schemas don't carry field descriptions, each result also includes a
  `note` string with units, formulas and caveats - read it to interpret values.
- Values use these unit conventions in key names: *_pct = percent, *_gold = gold,
  *_days / days_* = in-game days, *_xp = experience points.

Run:  python sdv_mcp_server.py     Requires: pip install "mcp[cli]".
"""
from __future__ import annotations
import os, sys, logging, functools, inspect, tempfile
from typing import Annotated, Literal, Any
try:
    from typing import TypedDict
except ImportError:
    from typing_extensions import TypedDict
from pydantic import Field
from mcp.server.fastmcp import FastMCP
import sdv_parser as P
import sdv_wiki as WIKI
import sdv_calc as CALC

log = logging.getLogger("sdv_mcp")

def setup_logging():
    """Configure logging to stderr (captured by MCP clients such as Claude Desktop)
    and, unless disabled, to a log file. Returns the log file path (or None).

    Env: SDV_LOG_LEVEL (default INFO), SDV_LOG_FILE (path; empty/"none" disables the
    file handler; default <tempdir>/sdv-mcp.log). Never writes to stdout - that is the
    stdio MCP protocol channel."""
    if getattr(setup_logging, "_done", False):
        return getattr(setup_logging, "_path", None)
    level = getattr(logging, os.environ.get("SDV_LOG_LEVEL", "INFO").upper(), logging.INFO)
    log.setLevel(level)
    log.propagate = False
    fmt = logging.Formatter("%(asctime)s [%(levelname)s] sdv-mcp: %(message)s")
    sh = logging.StreamHandler(sys.stderr); sh.setFormatter(fmt); log.addHandler(sh)
    path = os.environ.get("SDV_LOG_FILE")
    if path is None:
        path = os.path.join(tempfile.gettempdir(), "sdv-mcp.log")
    elif path.strip().lower() in ("", "none", "off", "0"):
        path = None
    if path:
        try:
            fh = logging.FileHandler(path, encoding="utf-8"); fh.setFormatter(fmt)
            log.addHandler(fh)
        except OSError as e:
            log.warning("could not open log file %s: %s", path, e); path = None
    setup_logging._done = True; setup_logging._path = path
    return path

def _wrap_tool_for_logging(name, fn):
    """Wrap a tool callable so any exception is logged with a full traceback before
    it propagates. Without this, a raised tool surfaces to the client only as an
    opaque output-schema error ('None is not of type object') with no server detail."""
    if getattr(fn, "_sdv_logged", False):
        return fn
    if inspect.iscoroutinefunction(fn):
        @functools.wraps(fn)
        async def wrapper(*args, **kwargs):
            try:
                return await fn(*args, **kwargs)
            except Exception:
                log.exception("tool '%s' raised (kwargs=%r)", name, kwargs)
                raise
    else:
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            try:
                return fn(*args, **kwargs)
            except Exception:
                log.exception("tool '%s' raised (kwargs=%r)", name, kwargs)
                raise
    wrapper._sdv_logged = True
    return wrapper

def install_tool_logging():
    """Attach the exception-logging wrapper to every registered tool."""
    for name, tool in mcp._tool_manager._tools.items():
        tool.fn = _wrap_tool_for_logging(name, tool.fn)

def _make_property_nullable(prop):
    """Allow JSON null for one output-schema property in place."""
    if not isinstance(prop, dict):
        return
    if "type" in prop:
        t = prop["type"]
        if isinstance(t, str) and t != "null":
            prop["type"] = [t, "null"]
        elif isinstance(t, list) and "null" not in t:
            prop["type"] = [*t, "null"]
    elif "anyOf" in prop or "oneOf" in prop:
        key = "anyOf" if "anyOf" in prop else "oneOf"
        opts = prop[key]
        if not any(isinstance(s, dict) and s.get("type") == "null" for s in opts):
            opts.append({"type": "null"})
    elif "$ref" in prop:
        prop["anyOf"] = [{"$ref": prop.pop("$ref")}, {"type": "null"}]

def relax_output_schemas():
    """Mark every field of every tool's OUTPUT schema as nullable.

    FastMCP builds a Pydantic model from each tool's TypedDict return type in which
    all fields default to None, then serialises ALL of them - including unset ones -
    as JSON null. Tools legitimately return a sparse subset of their declared fields,
    so strict clients (e.g. Claude Desktop) that validate structured output reject
    those nulls ('None is not of type object/string'). Advertising the fields as
    nullable is accurate (they are optional) and lets that null pass validation."""
    for tool in mcp._tool_manager._tools.values():
        schema = tool.output_schema
        if not schema:
            continue
        for prop in schema.get("properties", {}).values():
            _make_property_nullable(prop)

mcp = FastMCP("sdv-mcp")

# ---- reusable annotated parameter types -----------------------------------
SavePath = Annotated[str, Field(description="Path to a save file OR a save folder (e.g. .../Saves/Farm_123 "
                                            "or .../Saves/Farm_123/Farm_123). Leave empty to use the save "
                                            "configured at server startup (--save/--save-dir or SDV_SAVE_PATH/"
                                            "SDV_SAVE_DIR). The server never auto-discovers saves; one must be "
                                            "configured or passed explicitly.")]
PlayerName = Annotated[str, Field(description="Player/farmhand name; empty = host player.")]
Season = Literal["", "spring", "summer", "fall", "winter"]
Weather = Literal["", "sunny", "rain"]
Quality = Literal["normal", "silver", "gold", "iridium"]
AutoBool = Literal["auto", "true", "false"]
Skill = Literal["farming", "fishing", "foraging", "mining", "combat"]

# Default save configured at startup: env var now, CLI arg may override in __main__.
# May be a save FILE or a save FOLDER. Required - the server does not auto-discover.
DEFAULT_SAVE = os.environ.get("SDV_SAVE_PATH") or os.environ.get("SDV_SAVE_DIR") or ""

def _save_file_in_dir(d):
    """Given a Stardew save FOLDER, return its main save file. Stardew names the
    file the same as the folder; fall back to the first non-backup file."""
    base = os.path.basename(os.path.normpath(d))
    cand = os.path.join(d, base)
    if os.path.isfile(cand):
        return cand
    for f in sorted(os.listdir(d)):
        fp = os.path.join(d, f)
        if os.path.isfile(fp) and not f.endswith("_old") and not f.startswith("SaveGameInfo"):
            return fp
    raise ValueError(f"No Stardew save file found in directory: {d}")

def _resolve(save_path: str = ""):
    """Resolve a save FILE or FOLDER to (parsed_root, file_path). Precedence:
    explicit save_path arg > startup default (DEFAULT_SAVE). The server never
    scans the machine for saves - one must be configured or passed explicitly."""
    target = save_path or DEFAULT_SAVE
    if not target:
        raise ValueError("No save configured. Set one at startup with --save FILE / --save-dir DIR "
                         "or the SDV_SAVE_PATH / SDV_SAVE_DIR env var, or pass save_path on the call. "
                         "This server does not auto-discover saves.")
    if os.path.isdir(target):
        target = _save_file_in_dir(target)
    if not os.path.isfile(target):
        raise ValueError(f"No save file at: {target}")
    return P.load_save(target), target

# ---- optional tool gating (disable tools deemed "cheating"/unfair) ---------
def _csv(v):
    return [t.strip() for t in (v or "").split(",") if t.strip()]

def apply_tool_policy(disable=None, enable=None):
    """Prune the registered tool set. `enable` (allowlist) keeps only those tools;
    `disable` (denylist) removes tools. Unknown names are warned and ignored.
    Returns (removed, unknown)."""
    names = set(mcp._tool_manager._tools)
    disable = set(disable or []); enable = set(enable or [])
    unknown = sorted((disable | enable) - names)
    keep = (enable & names) if enable else set(names)
    keep -= disable
    removed = sorted(names - keep)
    for n in removed:
        mcp.remove_tool(n)
    return removed, unknown

def tool_policy_from_config(args=None):
    """Resolve disable/enable lists: CLI arg overrides the env var for each."""
    dis = _csv(getattr(args, "disable_tools", None)) or _csv(os.environ.get("SDV_DISABLE_TOOLS"))
    ena = _csv(getattr(args, "enable_tools", None)) or _csv(os.environ.get("SDV_ENABLE_TOOLS"))
    return dis, ena

# ======================= output schemas (calculators) =====================
class SkillForecast(TypedDict, total=False):
    player: str; skill: str; current_level: int; current_xp: int
    target_level: int; target_xp: int; xp_remaining: int
    xp_per_action: int; action: str; actions_needed: int; note: str; error: str

class ProcessingPlan(TypedDict, total=False):
    days: int; artisan: bool; kegs_owned: int; jars_owned: int
    keg_items_held: int; fruit: int; veg: int; special: int
    cycles_per_keg: dict; kegs_needed_to_clear_in_days: int; kegs_to_build: int
    est_gross_gold: int; items_priced: int; items_without_price: dict; note: str

class CropPlan(TypedDict, total=False):
    season: str; days_left: int; crops: list; budget: int
    best_crop_tiles_affordable: dict; tiller_applied: bool; note: str; note_empty: str

class FriendshipForecast(TypedDict, total=False):
    player: str; villager: str; current_points: int; current_hearts: int
    target_hearts: int; points_remaining: int; loved_gifts_needed: int
    weeks_at_2_loved_per_week: int; note: str; error: str; known: list

class SprinklerPlan(TypedDict, total=False):
    sprinkler: str; tiles: int; coverage_each: int; sprinklers_needed: int
    materials_needed: dict; materials_on_hand: dict; buildable_now: int
    shortfall: dict; note: str; error: str

class ProcessingValue(TypedDict, total=False):
    item: str; base_price: int; kind: str; artisan: bool; tiller: bool
    quality_for_raw: str; values: dict; best: str; best_value: int; note: str; error: str

class FishPondForecast(TypedDict, total=False):
    from_: str; forecast: dict; ponds: list; note: str

class QualityOdds(TypedDict, total=False):
    base_farming_level: int; food_buff: int; effective_farming_level: int
    fertilizer_level: int; iridium_pct: float; gold_pct: float
    silver_pct: float; normal_pct: float; note: str; error: str

class AnimalQuality(TypedDict, total=False):
    from_: str; result: dict; animals: list; animal_type: str; note: str; error: str

class AnimalValue(TypedDict, total=False):
    product: str; base_price: int; rancher: bool; artisan: bool
    values: dict; best: str; note: str; error: str

class FishingForecast(TypedDict, total=False):
    player: str; current_fishing_level: int; current_xp: int; target_level: int
    target_xp: int; xp_remaining: int; fish: str; difficulty: int; quality: str
    perfect: bool; treasure: bool; legendary: bool; xp_per_catch: int
    catches_needed: int; note: str; error: str; known_fish: list

# ============================ save/status tools ============================
@mcp.tool()
def overview(save_path: SavePath = "") -> dict:
    """Headline state: farm name, players, in-game date, shared money, lifetime
    earnings, deepest mine level, game version."""
    root, _ = _resolve(save_path); return P.overview(root)

@mcp.tool()
def players(save_path: SavePath = "") -> list:
    """Every player: skill levels, XP, XP-to-next-level, professions, spouse,
    backpack size, house-upgrade level."""
    root, _ = _resolve(save_path); return P.players(root)

@mcp.tool()
def community_center(save_path: SavePath = "") -> dict:
    """Community Center: rooms done/left, every incomplete bundle with exact items
    still required, and Vault payment status."""
    root, _ = _resolve(save_path); return P.community_center(root)

_BUNDLE_LOCK_HINTS = [
    (("desert trader", "calico desert", "the desert", "sandy's", "oasis"), "desert"),
    (("krobus", "sewer"), "sewers"),
    (("skull cavern",), "skull_cavern"),
    (("casino",), "casino"),
    (("ginger island", "island trader", "volcano", "gourmand", "professor snail", "pirate cove"), "ginger_island"),
]

@mcp.tool()
def bundle_sourcing(
    save_path: SavePath = "",
    research: Annotated[bool, Field(description="Fetch a wiki how_to_obtain summary for each missing bundle item. Needs network.")] = True,
    research_limit: Annotated[int, Field(description="Max distinct items to research (caps wiki calls).", ge=1, le=40)] = 20,
) -> dict:
    """Incomplete Community Center bundles with, for each still-needed item, a wiki
    how-to-obtain summary AND reachability hints: if the summary references a gated
    location that isn't unlocked in this save (e.g. Desert, Ginger Island), it's
    flagged via locked_source_hints (a hint - the item may have an ungated source
    too). Includes the full `unlocks` snapshot."""
    root, _ = _resolve(save_path)
    cc = P.community_center(root)
    unlk = P.unlocks(root)
    items = {}
    for b in cc.get("incomplete_bundles", []):
        for it in b.get("items_remaining", []):
            items.setdefault(it, []).append(f"{b['room']}/{b['bundle']}")
    sourcing = {}
    if research:
        for item in list(items)[:research_limit]:
            sm = WIKI.summary(item)
            text = (sm.get("summary") or "")
            entry = {"how_to_obtain": text or None, "url": sm.get("url"), "locked_source_hints": []}
            low = text.lower()
            for keywords, area_key in _BUNDLE_LOCK_HINTS:
                if any(k in low for k in keywords):
                    area = unlk["areas"].get(area_key)
                    if isinstance(area, dict) and not area["unlocked"]:
                        entry["locked_source_hints"].append({"area": area_key, "requires": area.get("requires")})
            sourcing[item] = entry
    return {"incomplete_bundles": cc.get("incomplete_bundles", []),
            "missing_items": {k: v for k, v in items.items()},
            "sourcing": sourcing,
            "unlocks": unlk["areas"],
            "note": "missing_items maps each still-needed item to the bundles wanting it. sourcing["
                    "item].how_to_obtain is the wiki acquisition summary. locked_source_hints flags "
                    "when the summary REFERENCES a location that isn't unlocked in this save - it is a "
                    "HINT, not proof the item is unreachable (many items have an alternate ungated "
                    "source, e.g. Pufferfish at the Beach). Read how_to_obtain to confirm whether an "
                    "open source exists. Cross-check quality/quantity in `community_center`."}

@mcp.tool()
def inventory(save_path: SavePath = "",
              full: Annotated[bool, Field(description="List every chest item instead of just the top 40 (merged view only).")] = False,
              by_container: Annotated[bool, Field(description="Return a per-chest breakdown (type, location, tile, color, contents) instead of the merged bag.")] = False) -> dict:
    """Items held: each player's backpack plus chest contents. Default merges all
    chests into one bag; set by_container=True for a per-container breakdown."""
    root, _ = _resolve(save_path); return P.inventory(root, full=full, by_container=by_container)

@mcp.tool()
def processing(save_path: SavePath = "") -> dict:
    """Keg/jar planning data: held crops grouped into fruit/veg/special (by the
    save's own item category) + machine counts. Modded items are excluded and
    listed separately."""
    root, _ = _resolve(save_path); return P.processing(root)

@mcp.tool()
def feed(save_path: SavePath = "") -> dict:
    """Animal feed status: animals, silo hay, fiber, and days of feed covered."""
    root, _ = _resolve(save_path); return P.feed(root)

@mcp.tool()
def museum(save_path: SavePath = "") -> dict:
    """Museum donations out of 95 and the next milestone (e.g. 60 = Rusty Key)."""
    root, _ = _resolve(save_path); return P.museum(root)

@mcp.tool()
def monster_goals(save_path: SavePath = "") -> list:
    """Adventurer's Guild eradication goals: kills vs target + reward per category."""
    root, _ = _resolve(save_path); return P.monster_goals(root)

@mcp.tool()
def friendships(save_path: SavePath = "") -> dict:
    """Per-player villager hearts/points and spouse status."""
    root, _ = _resolve(save_path); return P.friendships(root)

@mcp.tool()
def perfection(save_path: SavePath = "") -> dict:
    """Full weighted Perfection %: the 11 in-game categories (shipped, obelisks,
    golden clock, monster slayer, great friends, skills, stardrops, cooking,
    crafting, fish, walnuts) with each one's have/total and earned %. Verified weights."""
    root, _ = _resolve(save_path); return P.perfection(root)

@mcp.tool()
def fish_available(save_path: SavePath = "", season: Season = "", weather: Weather = "",
                   only_uncaught: Annotated[bool, Field(description="Hide fish the host already caught.")] = False) -> dict:
    """Fish catchable under given conditions (defaults to the save's current season,
    any weather). Each entry lists seasons, weather, locations, time, already-caught."""
    root, _ = _resolve(save_path)
    return P.fish_available(root, season=season or None, weather=weather or None, only_uncaught=only_uncaught)

@mcp.tool()
def player_tools(save_path: SavePath = "") -> dict:
    """Each player's tools (pickaxe/axe/hoe/watering can/rod) and upgrade tier."""
    root, _ = _resolve(save_path); return P.tools(root)

@mcp.tool()
def wallet(save_path: SavePath = "") -> dict:
    """Special keys/items owned (Rusty Key, Skull Key, Club Card, etc.). Reads
    1.6 mail flags + legacy booleans, so it's correct on 1.5 and 1.6 saves."""
    root, _ = _resolve(save_path); return P.wallet(root)

@mcp.tool()
def unlocks(save_path: SavePath = "") -> dict:
    """Which gated locations/vendors are reachable in THIS save (Desert + Desert
    Trader, Sewers/Krobus, Skull Cavern, Casino, Quarry, Greenhouse, Minecarts,
    Movie Theater, Adventurer's Guild, Ginger Island) with what each gates and, if
    locked, how to unlock it. Use this to filter item-acquisition advice to what's
    actually available (e.g. don't suggest the Desert Trader if the bus isn't fixed)."""
    root, _ = _resolve(save_path); return P.unlocks(root)

@mcp.tool()
def can_complete_now(save_path: SavePath = "") -> dict:
    """Incomplete CC bundles finishable from items currently held (presence-only)."""
    root, _ = _resolve(save_path); return P.can_complete_now(root)

@mcp.tool()
def missing_museum(save_path: SavePath = "") -> dict:
    """Undonated museum items (minerals + artifacts) with sourcing notes."""
    root, _ = _resolve(save_path); return P.missing_museum(root)

@mcp.tool()
def mods(save_path: SavePath = "") -> dict:
    """Detect mods and list what couldn't be mapped to vanilla references
    (modded item ids, unmapped bundle/museum entries)."""
    root, _ = _resolve(save_path); return P.detect_mods(root)

@mcp.tool()
def missing_recipes(save_path: SavePath = "") -> dict:
    """Per player: cooking + crafting recipes you've LEARNED but not yet made
    (make these to progress Perfection), with known/made counts and how many you
    still haven't learned. Pairs with `perfection` Cooking/Crafting categories."""
    root, _ = _resolve(save_path); return P.missing_recipes(root)

@mcp.tool()
def shipping_tracker(save_path: SavePath = "") -> dict:
    """What the host has shipped (basicShipped) by name with lifetime quantities,
    plus distinct count vs the 154-item Full Shipment / perfection target."""
    root, _ = _resolve(save_path); return P.shipping_tracker(root)

@mcp.tool()
def golden_walnuts(save_path: SavePath = "") -> dict:
    """Golden Walnut progress on Ginger Island: found vs 130, unspent balance,
    whether the island is unlocked, and repeatable-source progress."""
    root, _ = _resolve(save_path); return P.golden_walnuts(root)

@mcp.tool()
def full_report(save_path: SavePath = "") -> dict:
    """Everything at once: overview, players, CC, inventory, processing, feed,
    museum, monster goals, friendships, perfection, tools, wallet, mods."""
    root, _ = _resolve(save_path); return P.full_report(root)

# ============================ wiki verification ============================
@mcp.tool()
def wiki_search(query: Annotated[str, Field(description="Search terms, e.g. 'sturgeon' or 'squid fest'.")],
                limit: Annotated[int, Field(description="Max results.", ge=1, le=20)] = 6) -> dict:
    """Full-text search the Stardew Valley Wiki (titles + snippets)."""
    return WIKI.search(query, limit=limit)

@mcp.tool()
def wiki_page(title: Annotated[str, Field(description="Exact page title, e.g. 'Sturgeon'. Redirects are followed.")],
              section: Annotated[str, Field(description="Optional heading (e.g. 'Prizes', 'Fish Pond') to return only that section.")] = "",
              raw: Annotated[bool, Field(description="Return raw wikitext instead of cleaned text.")] = False) -> dict:
    """Fetch a wiki page as cleaned plain text - to VERIFY facts and pull context
    (prices, seasons, locations, event schedules)."""
    return WIKI.page(title, section=section or None, raw=raw)

@mcp.tool()
def wiki_infobox(title: Annotated[str, Field(description="Exact page title, e.g. 'Sturgeon'.")]) -> dict:
    """A page's infobox as structured key/value fields (price/season/location) -
    the most reliable surface for verification."""
    return WIKI.infobox(title)

@mcp.tool()
def how_to_obtain(item: Annotated[str, Field(description="Item name, e.g. 'Bat Wing', 'Cauliflower', 'Solar Essence'.")]) -> dict:
    """How to get an item: the wiki's lead-section summary of every acquisition
    method (monster drops, shop purchases, trades, gifting, crafting) plus the
    structured infobox (source/season/price). Use this to plan the best way to
    obtain a quest/bundle item. Call wiki_page(item) for full drop-rate detail."""
    sm = WIKI.summary(item); ib = WIKI.infobox(item)
    if sm.get("error") and ib.get("error"):
        return {"item": item, "error": sm.get("error")}
    return {"item": sm.get("title") or item, "how_to_obtain": sm.get("summary"),
            "fields": ib.get("fields"), "url": sm.get("url") or ib.get("url"),
            "source": "Stardew Valley Wiki (CC BY-NC-SA)",
            "note": "Summary lists the acquisition methods; some (Desert Trader, Krobus, "
                    "Skull Cavern, Casino, Ginger Island) require an unlocked location - "
                    "call `unlocks` to check what's reachable in this save before recommending "
                    "a method, and combine with deepest mine level/season. wiki_page(item) has "
                    "drop rates/floors."}

# ============================== calculators ================================
@mcp.tool()
def skill_xp_forecast(
    skill: Annotated[Skill, Field(description="Which skill to forecast.")],
    target_level: Annotated[int, Field(description="Goal level 1-10.", ge=1, le=10)],
    save_path: SavePath = "",
    player: PlayerName = "",
    item_price: Annotated[int, Field(description="Base sell price of a crop harvest -> uses the farming XP formula. 0 = unused.")] = 0,
    per_action_xp: Annotated[int, Field(description="XP per action override (e.g. 5 for petting/collecting; use for fishing). 0 = unused.")] = 0,
) -> SkillForecast:
    """Actions needed to reach a target skill level from current save XP. Supply
    item_price (crop harvest) OR per_action_xp. Food buffs do NOT change XP."""
    root, _ = _resolve(save_path)
    return CALC.skill_xp_forecast(root, skill, target_level, player=player or None,
                                  item_price=item_price or None, per_action_xp=per_action_xp or None)

@mcp.tool()
def processing_planner(
    save_path: SavePath = "",
    days: Annotated[int, Field(description="Planning horizon in in-game days.", ge=1)] = 28,
    extra_kegs: Annotated[int, Field(description="Hypothetical extra kegs to add.")] = 0,
    extra_jars: Annotated[int, Field(description="Hypothetical extra jars to add.")] = 0,
    artisan: Annotated[AutoBool, Field(description="Apply Artisan +40%: auto-detect from professions, or force.")] = "auto",
) -> ProcessingPlan:
    """From held crops + machines owned: kegs/jars needed to clear the backlog in
    `days` and estimated gross gold (see `note` for multipliers/cycle-day caveats)."""
    root, _ = _resolve(save_path)
    art = None if artisan == "auto" else (artisan == "true")
    return CALC.processing_planner(root, days=days, extra_kegs=extra_kegs, extra_jars=extra_jars, artisan=art)

@mcp.tool()
def crop_planner(
    save_path: SavePath = "",
    season: Season = "",
    days_left: Annotated[int, Field(description="Days remaining in the season. 0 = derive from save date.")] = 0,
    budget: Annotated[int, Field(description="Gold budget for the best-crop tile calc. 0 = skip.")] = 0,
    top: Annotated[int, Field(description="How many crops to return.", ge=1)] = 12,
    fertilizer: Annotated[int, Field(description="Fertilizer level for quality weighting: 0 none, 1 Basic, 2 Quality, 3 Deluxe.", ge=0, le=3)] = 0,
    quality_weighted: Annotated[bool, Field(description="Weight prices by expected crop quality (uses best farming level + fertilizer).")] = False,
) -> CropPlan:
    """Which crops fully mature in the window and profit per tile. Tiller +10%
    auto-applied. Base prices unless quality_weighted."""
    root, _ = _resolve(save_path)
    return CALC.crop_planner(root, season=season or None, days_left=days_left or None,
                             budget=budget or None, top=top, fertilizer=fertilizer,
                             quality_weighted=quality_weighted)

@mcp.tool()
def friendship_forecast(
    villager: Annotated[str, Field(description="Villager name, e.g. 'Robin'.")],
    target_hearts: Annotated[int, Field(description="Goal heart level.", ge=1, le=14)] = 10,
    save_path: SavePath = "",
    player: PlayerName = "",
    loved_gifts_per_week: Annotated[int, Field(description="Loved gifts given per week (max 2).", ge=0, le=2)] = 2,
) -> FriendshipForecast:
    """Loved gifts + weeks to reach a target heart level from current save points."""
    root, _ = _resolve(save_path)
    return CALC.friendship_forecast(root, villager, target_hearts=target_hearts,
                                    player=player or None, loved_gifts_per_week=loved_gifts_per_week)

@mcp.tool()
def sprinkler_plan(
    tiles: Annotated[int, Field(description="Number of tilled tiles to water.", ge=1)],
    save_path: SavePath = "",
    sprinkler: Annotated[Literal["Basic", "Quality", "Iridium"], Field(description="Sprinkler type (coverage 4/8/24).")] = "Quality",
) -> SprinklerPlan:
    """Sprinklers + materials to water `tiles`, and whether the save's bars can build them."""
    root, _ = _resolve(save_path)
    return CALC.sprinkler_plan(root, tiles, sprinkler=sprinkler)

@mcp.tool()
def processing_value(
    item: Annotated[str, Field(description="Crop name, e.g. 'Cranberries'.")],
    save_path: SavePath = "",
    base_price: Annotated[int, Field(description="Override base sell price. 0 = look up.")] = 0,
    kind: Annotated[Literal["", "fruit", "veg"], Field(description="Force fruit/veg; empty = auto-detect from save.")] = "",
    quality: Annotated[Quality, Field(description="Star quality for the raw-sale comparison.")] = "normal",
    artisan: Annotated[AutoBool, Field(description="Apply Artisan +40%: auto/true/false.")] = "auto",
) -> ProcessingValue:
    """Rank ways to sell a crop: raw (Tiller + quality) vs keg (wine/juice) vs jar
    (jelly/pickle). See `note` for multipliers."""
    root, _ = _resolve(save_path)
    art = None if artisan == "auto" else (artisan == "true")
    return CALC.processing_value(root, item, base_price=base_price or None, kind=kind or None,
                                 quality=quality, artisan=art)

@mcp.tool()
def fish_pond_forecast(
    save_path: SavePath = "",
    fish: Annotated[str, Field(description="Model a hypothetical pond of this fish; empty = read save's ponds.")] = "",
    current_pop: Annotated[int, Field(description="Current population for the hypothetical. -1 = unknown.")] = -1,
    capacity: Annotated[int, Field(description="Target capacity (1-10).", ge=1, le=10)] = 10,
    spawn_days: Annotated[int, Field(description="Override reproduction interval in days. 0 = use table.")] = 0,
) -> FishPondForecast:
    """Days to fill a fish pond to capacity via reproduction."""
    root, _ = _resolve(save_path)
    return CALC.fish_pond_forecast(root, fish=fish or None,
                                   current_pop=None if current_pop < 0 else current_pop,
                                   capacity=capacity, spawn_days=spawn_days or None)

@mcp.tool()
def crop_quality_odds(
    save_path: SavePath = "",
    farming_level: Annotated[int, Field(description="Farming level 0-10; -1 = use save's level.")] = -1,
    fertilizer: Annotated[int, Field(description="0 none, 1 Basic, 2 Quality, 3 Deluxe.", ge=0, le=3)] = 0,
    food_buff: Annotated[int, Field(description="Farming levels from food (e.g. 3 = Farmer's Lunch); effective level caps at 14.", ge=0)] = 0,
    player: PlayerName = "",
) -> QualityOdds:
    """Gold/silver/normal (and iridium with Deluxe) crop-quality percentages."""
    root, _ = _resolve(save_path)
    return CALC.crop_quality_odds(farming_level=None if farming_level < 0 else farming_level,
                                  fertilizer=fertilizer, food_buff=food_buff, root=root, player=player or None)

@mcp.tool()
def list_buffs(skill: Annotated[str, Field(description="Filter by skill (farming/fishing/...); empty = all.")] = "") -> dict:
    """Food/consumable buffs that raise a skill LEVEL (Farmer's Lunch +3, Trout
    Soup +1). These change level-dependent effects, NOT XP gain."""
    return CALC.list_buffs(skill=skill or None)

@mcp.tool()
def animal_product_quality(
    save_path: SavePath = "",
    friendship: Annotated[int, Field(description="Model one animal: friendship 0-1000. -1 = read save's animals.")] = -1,
    mood: Annotated[int, Field(description="Mood/happiness 0-255 for the hypothetical.")] = -1,
    animal_type: Annotated[str, Field(description="Animal type label for the hypothetical.")] = "",
    profession_bonus: Annotated[bool, Field(description="Apply +0.333 Coopmaster/Shepherd bonus for the hypothetical.")] = False,
) -> AnimalQuality:
    """Iridium/gold/silver/normal produce odds per animal (friendship + mood +
    Coopmaster/Shepherd). Reads all save animals, or models one."""
    root, _ = _resolve(save_path)
    return CALC.animal_product_quality(root=root,
        friendship=None if friendship < 0 else friendship,
        mood=None if mood < 0 else mood, animal_type=animal_type or None,
        profession_bonus=profession_bonus)

@mcp.tool()
def animal_product_value(
    product: Annotated[str, Field(description="Raw product, e.g. 'Milk', 'Large Milk', 'Egg', 'Wool'.")],
    save_path: SavePath = "",
    quality: Annotated[Quality, Field(description="Star quality for the raw-sale comparison.")] = "normal",
    rancher: Annotated[AutoBool, Field(description="Apply Rancher +20% to raw: auto/true/false.")] = "auto",
    artisan: Annotated[AutoBool, Field(description="Apply Artisan +40% to the processed good: auto/true/false.")] = "auto",
) -> AnimalValue:
    """Raw (Rancher +20% + quality) vs processed (Artisan +40%) value of an animal product."""
    root, _ = _resolve(save_path)
    rc = None if rancher == "auto" else (rancher == "true")
    ar = None if artisan == "auto" else (artisan == "true")
    return CALC.animal_product_value(root, product, quality=quality, rancher=rc, artisan=ar)

@mcp.tool()
def fishing_xp_forecast(
    target_level: Annotated[int, Field(description="Goal fishing level 1-10.", ge=1, le=10)],
    save_path: SavePath = "",
    difficulty: Annotated[int, Field(description="Fish difficulty 5-110. 0 = look up from `fish`.", ge=0, le=110)] = 0,
    fish: Annotated[str, Field(description="Known fish name to look up difficulty, e.g. 'Sturgeon'.")] = "",
    quality: Annotated[Quality, Field(description="Fish quality used in the XP formula.")] = "normal",
    perfect: Annotated[bool, Field(description="Perfect catch (x2.4).")] = False,
    treasure: Annotated[bool, Field(description="Caught a treasure chest (x2.2).")] = False,
    legendary: Annotated[bool, Field(description="Legendary fish (x5).")] = False,
    player: PlayerName = "",
) -> FishingForecast:
    """Catches needed to reach a target fishing level from save XP.
    XP = ((quality+1)*3) + (difficulty/3), x-multipliers stack (see `note`)."""
    root, _ = _resolve(save_path)
    return CALC.fishing_xp_forecast(root, target_level, difficulty=difficulty or None,
        fish=fish or None, quality=quality, perfect=perfect, treasure=treasure,
        legendary=legendary, player=player or None)

# ============================ player-life tools ============================
@mcp.tool()
def daily_briefing(save_path: SavePath = "") -> dict:
    """One-call morning digest from the save: date, daily luck, birthdays today +
    upcoming (and whether you hold a loved gift), festivals in the next 7 days,
    machines ready to collect, crops ready to harvest, and animals still to pet."""
    root, _ = _resolve(save_path); return P.daily_briefing(root)

@mcp.tool()
def gift_helper(save_path: SavePath = "",
                upcoming_days: Annotated[int, Field(description="Window for 'upcoming birthdays'.", ge=1, le=112)] = 14) -> dict:
    """Per-villager birthday (read from the save) + your current hearts + notable
    loved gifts, flagging which loved gifts you currently hold. Also lists
    birthdays within `upcoming_days`. Loved-gift lists are a curated summary -
    use wiki_page(villager) for the authoritative full list."""
    root, _ = _resolve(save_path); return P.gift_birthday(root, upcoming_days=upcoming_days)

@mcp.tool()
def ready_to_collect(save_path: SavePath = "") -> dict:
    """What's ready right now: placed machines whose product is ready to collect
    (kegs/jars/mayo/cheese/tappers/mushroom boxes/crab pots) and crops ready to
    harvest in tilled soil."""
    root, _ = _resolve(save_path)
    return {"machines_ready": P.machines_ready(root), "crops": P.crops_ready(root)}

@mcp.tool()
def villager_schedule(
    villager: Annotated[str, Field(description="Villager name, e.g. 'Abigail'.")],
    save_path: SavePath = "") -> dict:
    """A villager's daily schedule from the wiki, paired with YOUR save context
    (current date, weather, and hearts) so you can pick the matching conditional
    branch. Schedules depend on season/day/weather/hearts/events, so read the
    wiki text against the context provided."""
    root, _ = _resolve(save_path)
    ov = P.overview(root)
    is_rain = next((e.text for e in root.iter('isRaining')), 'false') == 'true'
    fr = P.friendships(root).get(ov['host'], {})
    hearts = next((r['hearts'] for r in fr.get('relationships', [])
                   if r['villager'].lower() == villager.lower()), None)
    sched = WIKI.page(villager, section='Schedule')
    return {'villager': villager,
            'your_context': {'date': f"{ov['date']['season'].title()} {ov['date']['day']}",
                             'day_of_week': ['Mon','Tue','Wed','Thu','Fri','Sat','Sun'][(ov['date']['day']-1)%7],
                             'raining': is_rain, 'your_hearts': hearts},
            'schedule': sched.get('content') or sched.get('error'),
            'source': sched.get('url'),
            'note': 'Pick the schedule branch matching your date/day-of-week/weather/hearts above. '
                    'Requires network for the wiki fetch.'}

@mcp.tool()
def chests(save_path: SavePath = "") -> dict:
    """Every container with identity + location: type (Chest/Stone Chest/Big Chest/
    special), map + tile (X,Y), color label, item count, and full contents."""
    root, _ = _resolve(save_path); return P.chests(root)

@mcp.tool()
def find_item(
    name: Annotated[str, Field(description="Item name to locate, e.g. 'Ancient Fruit'.")],
    save_path: SavePath = "",
    fuzzy: Annotated[bool, Field(description="Substring match (e.g. 'wine' finds all wines). False = exact name.")] = True,
) -> dict:
    """Locate an item across player backpacks, all chests, and machine outputs.
    Returns each place holding it with quantity and container location (map +
    tile + color) - answers 'where is my X?'."""
    root, _ = _resolve(save_path); return P.find_item(root, name, fuzzy=fuzzy)

@mcp.tool()
def net_worth(save_path: SavePath = "") -> dict:
    """Gold + sellable value of everything held (backpacks + chests + machine
    outputs), data-driven from each item's base sell price. Economy snapshot."""
    root, _ = _resolve(save_path); return P.net_worth(root)

@mcp.tool()
def quests(
    save_path: SavePath = "",
    research: Annotated[bool, Field(description="Fetch wiki context to explain how to complete each quest: "
                                                "the requested item's infobox (how/where to obtain) for item "
                                                "quests, plus a wiki search for the quest title. Needs network.")] = False,
    research_limit: Annotated[int, Field(description="Max quests to research when research=True (caps wiki calls).", ge=1, le=25)] = 8,
) -> dict:
    """Every player's active quest journal + the special-orders board. For item
    delivery/harvest/resource quests it names the requested item, counts how many
    are on hand (across all backpacks + chests), and flags `completable_now` when
    you already hold enough to turn in. Monster/fishing/socialize quests report
    progress counters. Set research=True to attach wiki guidance per quest."""
    root, _ = _resolve(save_path)
    data = P.quests(root)
    if research:
        # Research item-based quests first (their item infobox is the most useful),
        # so a limited wiki budget is spent where it helps most.
        all_q = [q for pl in data["players"] for q in pl["quests"]]
        def named_item(q):
            it = q.get("required_item")
            return it if (it and not str(it).startswith("#")) else None
        all_q.sort(key=lambda q: named_item(q) is None)
        seen = set(); budget = research_limit
        for q in all_q:
            if budget <= 0:
                break
            info = {}
            item = named_item(q)
            if item and item not in seen:
                seen.add(item)
                ib = WIKI.infobox(item)
                sm = WIKI.summary(item)
                info["item"] = {"name": item,
                                "how_to_obtain": sm.get("summary"),
                                "fields": ib.get("fields"),
                                "url": ib.get("url") or sm.get("url")}
            title = q.get("title")
            if title:
                hits = WIKI.search(title, limit=3).get("results") or []
                if hits:
                    info["quest_search"] = hits
            if info:
                q["wiki"] = info
                budget -= 1
        data["research_note"] = ("wiki 'item.how_to_obtain' summarises every acquisition method "
                                 "(drops, shops, trades, gifting); 'item.fields' add structured "
                                 "price/season/source; 'quest_search' links the quest's wiki entry. "
                                 f"Researched up to {research_limit} quests (item quests first). "
                                 "Some sources need an unlocked location - call `unlocks` to filter "
                                 "to what's reachable. For drop rates/mine floors call wiki_page(item).")
    return data

def _parse_args():
    import argparse
    ap = argparse.ArgumentParser(
        description="Stardew Valley save inspector - read-only MCP server.")
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--save", metavar="FILE",
                   help="Path to a specific save file (.../Saves/Farm_123/Farm_123).")
    g.add_argument("--save-dir", metavar="DIR",
                   help="Path to a save FOLDER (.../Saves/Farm_123); the main save file is "
                        "auto-located inside. Overrides SDV_SAVE_PATH/SDV_SAVE_DIR.")
    ap.add_argument("--disable-tools", metavar="a,b,c",
                   help="Comma-separated tool names to DISABLE (e.g. tools you consider "
                        "cheating). Overrides SDV_DISABLE_TOOLS.")
    ap.add_argument("--enable-tools", metavar="a,b,c",
                   help="Comma-separated ALLOWLIST - only these tools are served. "
                        "Overrides SDV_ENABLE_TOOLS. Applied before --disable-tools.")
    return ap.parse_args()

def main():
    """Console entry point (see [project.scripts] in pyproject.toml)."""
    global DEFAULT_SAVE
    _logpath = setup_logging()
    _args = _parse_args()
    if _args.save:
        DEFAULT_SAVE = _args.save
    elif _args.save_dir:
        DEFAULT_SAVE = _args.save_dir
    _disable, _enable = tool_policy_from_config(_args)
    if _disable or _enable:
        _removed, _unknown = apply_tool_policy(_disable, _enable)
        if _unknown:
            log.warning("unknown tool name(s) ignored: %s", ", ".join(_unknown))
        if _removed:
            log.info("disabled %d tool(s): %s", len(_removed), ", ".join(_removed))
    install_tool_logging()
    relax_output_schemas()
    log.info("starting sdv-mcp | save=%r | tools=%d | log_file=%s",
             DEFAULT_SAVE or "(none configured)", len(mcp._tool_manager._tools),
             _logpath or "(stderr only)")
    mcp.run()

if __name__ == "__main__":
    main()
