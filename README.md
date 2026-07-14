# Stardew Save MCP

Read-only MCP server that reads a Stardew Valley save and answers questions about it. 40 tools: parse the save, verify game rules against the wiki, run calculators, and locate stuff in chests. Built it because I wanted to ask "how many kegs to clear my backlog" or "where's my Ancient Fruit" and get an actual answer instead of alt-tabbing to the wiki.

Nothing writes to the save. Ever. It opens the file read-only, strips the trailing null padding the game leaves, parses with ElementTree, and hands back JSON. The save is your farm's *state*; the wiki is the game's *rules*; the calculators do the math. Keep those three straight and you don't get hallucinated numbers.

Works on any 1.5/1.6 save (host + all farmhands, any names). Tested against 1.6.15.

## Requirements
- Python 3.10+
- `pip install -r requirements.txt` (just the `mcp` SDK; wiki client uses stdlib `urllib`)

Keep the four modules in the same folder — the server imports the others from its own dir.

## Install into a client
Add to your MCP config (e.g. `claude_desktop_config.json`), absolute path to the server:
```json
{
  "mcpServers": {
    "stardew-save": {
      "command": "python",
      "args": ["/path/to/stardew-save-mcp/sdv_mcp_server.py"]
    }
  }
}
```
macOS/Linux use `python3`. Runs on stdio.

## Picking a save
Every tool takes an optional `save_path`. Leave it blank and it auto-discovers saves (Windows `%APPDATA%\StardewValley\Saves`, macOS/Linux `~/.config` + Application Support, Steam Proton). One save found = it uses it; several = call `list_saves` and pass the path. Point at the **main save file**, not the folder:
`.../Saves/FarmName_123456/FarmName_123456`

Homelab note: if the save lives on a NAS share, just pass its path. Reads are cached by file mtime, so repeated calls in a session are cheap and always reflect the last night's sleep (the game only writes on sleep).

## Tools (40)

### Save state
| Tool | What |
|------|------|
| `list_saves` | Discovered saves (farm + path) |
| `overview` | Date, players, shared money, lifetime earnings, deepest mine, version |
| `players` | Per-player levels, XP, XP-to-next, professions, spouse, backpack, house |
| `community_center` | Rooms done/left, incomplete bundles + exact items needed, Vault status |
| `museum` | Donations / 95 + next milestone (60 = Rusty Key) |
| `monster_goals` | Guild eradication goals: kills vs target + reward |
| `friendships` | Villager hearts/points + spouse, per player |
| `player_tools` | Each player's tools + upgrade tier |
| `wallet` | Keys/special items (Rusty Key, Skull Key, Club Card, ...) |
| `feed` | Animals, silo hay, fiber, days of feed covered (+ fiber-as-grass-starters) |
| `full_report` | All of the above in one shot |

### Inventory + location
| Tool | What |
|------|------|
| `inventory` | Backpacks + chests. `full=True` = all items; `by_container=True` = per-chest |
| `processing` | Held crops grouped fruit/veg/special by the save's own item category |
| `chests` | Every container: type (Chest/Stone/Big/special), map + tile, color, contents |
| `find_item` | Where is X? Searches backpacks, chests, machine outputs. Map + tile + color |
| `net_worth` | Gold + sellable value of everything held (from each item's own price) |

### Planning + completion
| Tool | What |
|------|------|
| `can_complete_now` | CC bundles you could finish from what's in your chests right now |
| `missing_museum` | Undonated minerals + artifacts, with where they drop |
| `perfection` | Real weighted Perfection %: 11 categories, each with have/total + earned % |
| `daily_briefing` | Morning digest: luck, birthdays, festivals, machines/crops ready, pets due |
| `gift_helper` | Birthdays (from save) + your hearts + loved gifts, flags what you already hold |
| `ready_to_collect` | Machines with product ready + crops ready to harvest |
| `fish_available` | Fish catchable now (season/weather/time), `only_uncaught` filters |
| `mods` | Detect mods; list what couldn't map to vanilla (modded ids, unmapped bundle/museum) |

### Calculators (save + verified game formulas)
| Tool | What |
|------|------|
| `skill_xp_forecast` | Actions to hit a target skill level (farming XP formula) |
| `fishing_xp_forecast` | Catches to a target fishing level (difficulty/perfect/treasure/legendary) |
| `processing_planner` | Kegs/jars to clear the crop backlog in N days + est. gross gold |
| `processing_value` | Raw vs wine/juice vs jelly/pickle for a crop (Tiller/Artisan/quality aware) |
| `crop_planner` | Crops that mature in the window + profit/tile (`quality_weighted` optional) |
| `crop_quality_odds` | Gold/silver/normal/iridium % from farming level + fertilizer + food buff |
| `sprinkler_plan` | Sprinklers + materials for N tiles, and whether your bars can build them |
| `fish_pond_forecast` | Days to fill a pond to capacity + roe notes |
| `friendship_forecast` | Loved gifts + weeks to a target heart level |
| `animal_product_quality` | Iridium/gold/silver produce odds per animal (friendship + mood + prof) |
| `animal_product_value` | Raw (Rancher) vs processed (Artisan) value of milk/egg/wool |
| `list_buffs` | Food buffs that raise a skill level (Farmer's Lunch +3, Trout Soup +1) |

### Wiki verification (live)
| Tool | What |
|------|------|
| `wiki_search` | Search the Stardew Valley Wiki (titles + snippets) |
| `wiki_page` | A page (or one section) as clean text — to verify facts / pull context |
| `wiki_infobox` | A page's infobox as structured fields (price/season/location) |
| `villager_schedule` | A villager's wiki schedule + your save's date/weather/hearts |

## How the model reads the output
Inputs have per-parameter descriptions and enums for constrained args (`quality` = normal/silver/gold/iridium, `artisan` = auto/true/false, etc.). The 11 calculator tools also declare an **output schema** (field names + types) so the shape is known up front. MCP output schemas can't carry field descriptions, so every result also has a `note` with units/formulas/caveats — read it. Unit conventions in key names: `*_pct` = percent, `*_gold` = gold, `*_days`/`days_*` = days, `*_xp` = XP.

## Mods
Item classification (keg fruit/veg) is data-driven from each item's own `<category>` in the save, so vanilla content of any version is covered automatically. Modded items get detected (namespaced ids with a dot) and **excluded from vanilla-reference totals but reported by name/qty** — see `mods` and `processing.modded_items_excluded`. Bundle structure is read from the save, so overhaul/remix CCs parse; modded item *names* the parser can't resolve show as `#id`. Full modded-name resolution (loading `Data/Objects` + the `Mods` folder) is intentionally not built yet.

## Verified, not guessed
The calculator constants were checked against the wiki, not pulled from memory: crop quality formula + multipliers (iridium 2x / gold 1.5x / silver 1.25x), farming + fishing XP formulas, Tiller +10% / Rancher +20% / Artisan +40%, keg/jar multipliers, sprinkler recipes, fish-pond reproduction, Perfection weights, animal-product prices. Reference tables (crops, prices, fish difficulty) live at the top of `sdv_calc.py` and `sdv_parser.py` — extend them, or cross-check anything with the `wiki_*` tools.

## Files
- `sdv_parser.py` — the read-only save parser (ElementTree)
- `sdv_wiki.py` — MediaWiki Action API client (api.php; the wiki's rest.php returns empty, so Action API it is), cached + rate-limited
- `sdv_calc.py` — the calculators + reference tables
- `sdv_mcp_server.py` — the 40 tools

## Known limits
- Vanilla + whatever this wiki documents. Modded content lives on separate wikis.
- Full Shipment / missing-recipes by *name* aren't built yet — `perfection` gives the counts.
- Wiki tools need outbound network. The save tools don't.
