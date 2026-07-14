# Stardew Valley Save Inspector — read-only MCP server

Exposes a Stardew Valley save file to an MCP client (Claude Desktop, Cowork,
etc.) as **structured, read-only data**. The server only ever *parses* the save
and returns facts — it never writes to it — so your game is never at risk. Any
recommendations are left to the assistant reading the data.

Works on **any** save (game 1.5 / 1.6), host + all farmhands, any farm/player
names. Tested against 1.6.15.

## Files
- `sdv_parser.py` — the parser core (ElementTree; JSON-returning functions).
- `sdv_mcp_server.py` — the MCP server wrapping the parser as tools.
- `requirements.txt` — Python dependency (`mcp`).

## Tool contract (for the calling model)
Every tool exposes a description plus an **input schema with per-parameter
descriptions and enums** for constrained choices (e.g. `quality` = normal/silver/gold/iridium, `artisan` = auto/true/false). The **calculator
tools also declare an output schema** (field names + types) so the model knows
the result shape in advance. MCP output schemas can't carry field descriptions,
so every result also includes a `note` string with units, formulas and caveats -
read it to interpret values. Unit conventions in key names: `*_pct` = percent,
`*_gold` = gold, `*_days`/`days_*` = in-game days, `*_xp` = experience points.

## Wiki verification tools
`wiki_search` / `wiki_page` / `wiki_infobox` query the Stardew Valley Wiki's
MediaWiki **Action API** (`api.php`) live, to verify game facts and pull context
the save can't provide. (The wiki's REST API `rest.php` returns empty, so the
Action API is used.) Responses are cached in-process and rate-limited; a
descriptive User-Agent and `maxlag` are sent. Requires outbound network access.
Wiki content is CC BY-NC-SA - cite it when reproducing.

## Requirements
- Python 3.10+
- `pip install -r requirements.txt`  (installs the `mcp` SDK)

## Install
```bash
pip install -r requirements.txt
```
Keep `sdv_parser.py` and `sdv_mcp_server.py` in the same folder (the server
imports the parser from its own directory).

## Configure your MCP client
Add to your client's MCP config (e.g. `claude_desktop_config.json`):
```json
{
  "mcpServers": {
    "stardew-save": {
      "command": "python",
      "args": ["C:\\path\\to\\stardew_mcp\\sdv_mcp_server.py"]
    }
  }
}
```
Use the absolute path to `sdv_mcp_server.py`. On macOS/Linux use `python3`.

## Save-file selection
Every tool takes an optional `save_path`. If omitted, the server auto-discovers
saves in the standard locations (Windows `%APPDATA%\StardewValley\Saves`,
macOS/Linux `~/.config` and Application Support, and Steam Proton). If exactly
one save is found it's used; if several, call `list_saves` and pass the
`save_path` you want. Point at the **main save file**, e.g.
`.../Saves/FarmName_123456/FarmName_123456` (not the folder).

## Tools
| Tool | Returns |
|------|---------|
| `list_saves` | Discovered saves (farm name + path) |
| `overview` | Date, players, shared money, lifetime earnings, deepest mine, version |
| `players` | Per-player skill levels, XP, XP-to-next, professions, spouse, backpack, house |
| `community_center` | Rooms done/left, incomplete bundles + exact items needed, Vault status |
| `inventory` | Each backpack + chest contents (`full=True`; `by_container=True` for per-chest) |
| `processing` | Held crops grouped for keg/jar planning + kegs/jars owned |
| `feed` | Animals, silo hay, fiber, days of feed covered |
| `museum` | Donations / 95 and next milestone (e.g. Rusty Key at 60) |
| `monster_goals` | Adventurer's Guild eradication progress + rewards |
| `friendships` | Villager hearts/points per player + spouse |
| `perfection` | Museum %, CC %, monster-goal %, fish caught, recipes known |
| `fish_available` | Fish catchable by season/weather/time; `only_uncaught=True` filters |
| `player_tools` | Each player's tools + upgrade tier (Base/Copper/Steel/Gold/Iridium) |
| `wallet` | Special keys/items owned (Rusty Key, Skull Key, Club Card, etc.) |
| `can_complete_now` | Incomplete CC bundles finishable from current inventory |
| `missing_museum` | Undonated museum items (minerals & artifacts) + sourcing |
| `mods` | Detect mods; list unmapped modded items/bundles/museum ids |
| `wiki_search` | Search the Stardew Valley Wiki (titles + snippets) |
| `wiki_page` | Fetch a wiki page (or one section) as clean text - for verification |
| `wiki_infobox` | A page's infobox as structured fields (price/season/location) |
| `skill_xp_forecast` | Actions to reach a target skill level (from save XP) |
| `processing_planner` | Kegs/jars to clear the crop backlog in N days + est. gold |
| `crop_planner` | Crops that mature in the window + profit per tile |
| `friendship_forecast` | Loved gifts/weeks to reach target hearts |
| `sprinkler_plan` | Sprinklers + materials to water N tiles (save-aware) |
| `processing_value` | Rank raw vs wine/juice vs jelly/pickle for a crop |
| `fish_pond_forecast` | Days to fill a fish pond to capacity + roe notes |
| `crop_quality_odds` | Gold/silver/normal % from farming level + fertilizer + food buff |
| `list_buffs` | Food buffs that raise a skill level (Farmer's Lunch, Trout Soup...) |
| `animal_product_quality` | Iridium/gold/silver produce odds per animal (friendship+mood) |
| `animal_product_value` | Raw (Rancher) vs processed (Artisan) value of milk/egg/wool |
| `fishing_xp_forecast` | Catches to reach a target fishing level (difficulty/perfect/treasure) |
| `daily_briefing` | Morning digest: luck, birthdays, festivals, machines/crops ready, pets |
| `gift_helper` | Villager birthdays (from save) + hearts + loved gifts you hold |
| `ready_to_collect` | Machines with product ready + crops ready to harvest |
| `villager_schedule` | A villager's wiki schedule paired with your save's date/weather/hearts |
| `chests` | Every container: type, location + tile, color, and contents |
| `find_item` | Locate an item across backpacks/chests/machines (map + tile + color) |
| `net_worth` | Gold + sellable value of all held items (data-driven) |
| `full_report` | All of the above in one call |

## Notes / extending
- **Read-only:** the parser opens the file for reading only and truncates the
  trailing null padding Stardew writes; it never modifies the save.
- **Caching:** parsed saves are cached by file mtime, so repeated calls in a
  session are fast and always reflect the last in-game save (Stardew writes on
  sleep).
- **Reference data** (item id→name map, fish season/weather table, bundle item
  IDs) lives at the top of `sdv_parser.py`. Extend `ITEM` and `FISH` to cover
  more items/fish; modded item IDs will show as `#<id>` until mapped.
- **Mods:** item classification (keg fruit/veg) is **data-driven from each item's
  own `<category>` field in the save**, so vanilla content of any version is
  covered automatically. Modded items are detected (namespaced ids) and are
  **excluded from vanilla-reference totals but reported by name/quantity** via the
  `mods` tool and `processing.modded_items_excluded`. Bundle structure is read from
  the save so modded/overhaul Community Centers parse; modded item *names* for
  ids the parser can't resolve appear as `#id`. Full modded-name resolution
  (loading `Data/Objects` + the `Mods` folder) is intentionally not implemented yet.
