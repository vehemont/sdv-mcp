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
import os
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

mcp = FastMCP("stardew-save")

# ---- reusable annotated parameter types -----------------------------------
SavePath = Annotated[str, Field(description="Path to the main save file (e.g. .../Saves/Farm_123/Farm_123). "
                                            "Leave empty to auto-discover the single save on this machine.")]
PlayerName = Annotated[str, Field(description="Player/farmhand name; empty = host player.")]
Season = Literal["", "spring", "summer", "fall", "winter"]
Weather = Literal["", "sunny", "rain"]
Quality = Literal["normal", "silver", "gold", "iridium"]
AutoBool = Literal["auto", "true", "false"]
Skill = Literal["farming", "fishing", "foraging", "mining", "combat"]

def _resolve(save_path: str = ""):
    if save_path:
        if not os.path.isfile(save_path):
            raise ValueError(f"No save file at: {save_path}")
        return P.load_save(save_path), save_path
    saves = P.find_saves()
    if not saves:
        raise ValueError("No Stardew saves found automatically. Pass save_path explicitly.")
    if len(saves) > 1:
        raise ValueError("Multiple saves found; pass save_path. Options: "
                         + "; ".join(f"{s['farm']} -> {s['path']}" for s in saves))
    return P.load_save(saves[0]['path']), saves[0]['path']

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
def list_saves() -> list:
    """List Stardew save files discovered on this machine (farm name + path)."""
    return P.find_saves()

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
    """Special keys/items owned (Rusty Key, Skull Key, Club Card, etc.)."""
    root, _ = _resolve(save_path); return P.wallet(root)

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

if __name__ == "__main__":
    mcp.run()
