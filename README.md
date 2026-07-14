# sdv-mcp

I recently got into the game with my wife and noticed I was spending more time reading the Stardew Wiki rather than playing, so I made this to answer the questions I had. This is a read-only MCP server that reads a Stardew Valley save and answers questions about it. It includes 40 tools, and also allows Stardew Wiki search through MediaWiki API. I made this with mainly vanilla in mind, so YMMV with mods. 

> 🚨 This MCP is read-only and should not cause any issues, but safety first is always the best approach! Use a save copy first, not an original. Stardew Valley makes a one-night-before backup automatically, denoted by the sufix _old in the filename.

## Requirements
- Python 3.10+
- `pip install -r requirements.txt` (just the `mcp` SDK; wiki client uses stdlib `urllib`)

Keep the four modules in the same folder — the server imports the others from its own dir.

## Install into a client

### Recommended: uvx (auto-download, npx-style)
Needs [uv](https://docs.astral.sh/uv/). uvx clones/builds/caches the repo and runs
it — no manual install, no venv:
```json
{
  "mcpServers": {
    "sdv-mcp": {
      "command": "uvx",
      "args": [
        "--from", "git+https://github.com/vehemont/sdv-mcp",
        "sdv-mcp",
        "--save-dir", "C:/Users/you/AppData/Roaming/StardewValley/Saves/FarmName_123456"
      ]
    }
  }
}
```
Pin a version with `git+https://github.com/vehemont/sdv-mcp@v0.1.0`. Once it's on
PyPI this collapses to `"args": ["sdv-mcp", "--save-dir", "..."]`.

### Alternative: run a local checkout
```json
{
  "mcpServers": {
    "sdv-mcp": {
      "command": "python",
      "args": [
        "/path/to/sdv-mcp/sdv_mcp_server.py",
        "--save-dir", "C:/Users/you/AppData/Roaming/StardewValley/Saves/FarmName_123456"
      ]
    }
  }
}
```
macOS/Linux use `python3`; `pip install -r requirements.txt` first.

Either way: runs on stdio. Point `--save-dir` at your save FOLDER (main file
auto-located) or `--save` at the file; skip both and it auto-discovers.

## Picking a save
Precedence for which save a tool reads:
1. An explicit `save_path` on the tool call (a save file **or** a save folder).
2. The save configured at server startup — `--save-dir DIR` / `--save FILE`, or the
   `SDV_SAVE_DIR` / `SDV_SAVE_PATH` env var. Set this once in the MCP config and you
   never pass `save_path` again. A CLI flag overrides the env var.
3. Auto-discovery (Windows `%APPDATA%\StardewValley\Saves`, macOS/Linux `~/.config`
   + Application Support, Steam Proton). One save = used; several = call `list_saves`
   and pass the path.

Either a folder (`.../Saves/FarmName_123456`) or the file
(`.../Saves/FarmName_123456/FarmName_123456`) works everywhere a save is accepted —
given a folder, the main save file is auto-located (ignores `_old` backups and
`SaveGameInfo`).

Env-var config example (instead of the CLI flag):
```json
"env": { "SDV_SAVE_DIR": "C:/Users/you/AppData/Roaming/StardewValley/Saves/FarmName_123456" }
``

## Disabling tools
Any tool you consider cheating/unfair can be turned off so the model never sees it.
Two knobs, both settable as a CLI arg (wins) or an env var:

- **Denylist** — `--disable-tools a,b,c` or `SDV_DISABLE_TOOLS=a,b,c`. Serves everything except those.
- **Allowlist** — `--enable-tools a,b,c` or `SDV_ENABLE_TOOLS=a,b,c`. Serves *only* those (disable is applied after).

```json
{
  "mcpServers": {
    "sdv-mcp": {
      "command": "python",
      "args": [
        "/path/to/sdv-mcp/sdv_mcp_server.py",
        "--save-dir", "C:/Users/you/AppData/Roaming/StardewValley/Saves/FarmName_123456",
        "--disable-tools", "find_item,missing_museum,perfection"
      ]
    }
  }
}
```

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
```

## Packaging
`pyproject.toml` makes this a real package: `uv build` produces a wheel, and the `sdv-mcp` console script maps to `sdv_mcp_server:main`. Publish with `uv publish`.

## Files
- `sdv_parser.py` — the read-only save parser (ElementTree)
- `sdv_wiki.py` — MediaWiki Action API client (api.php; the wiki's rest.php returns empty, so Action API it is), cached + rate-limited
- `sdv_calc.py` — the calculators + reference tables
- `sdv_mcp_server.py` — the 40 tools

## Known limits
- Vanilla + whatever this wiki documents. Modded content lives on separate wikis.
- Full Shipment / missing-recipes by *name* aren't built yet — `perfection` gives the counts.
- Wiki tools need outbound network. The save tools don't.
