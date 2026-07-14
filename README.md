# sdv-mcp

This is a read-only MCP server that reads a Stardew Valley save and answers questions about it, and is pulls your most recent save data per-call. I recently got into the game with my wife and noticed I was spending more time reading the Stardew Wiki rather than playing, so I made this to answer the questions I had. It includes 47 tools, and also allows Stardew Wiki search through MediaWiki API. I made this with mainly vanilla in mind, so YMMV with mods. 

> [!CAUTION]
> This MCP is read-only and should not cause any issues, but safety first is always the best approach! Use a save copy first, not an original. Then once you feel comfortable, you can point it at your real save to receive the save-per-night updates. 


Example questions that utilize the state of your save, tailoring responses to you depending on the season, day, location, and what you already have:
> "What is my best money maker that I should be utilizing?"  

> "What should I focus on next?"  

> "Can anything be completed with what I have?"  

> "Best way to get coal?"

> "Give me a priority step-by-step list on completing my fishing bundle."

> "Where is the chest that has the pearl I need to gift to Clint?"

## Requirements
- Python 3.10+
- `pip install -r requirements.txt` (just the `mcp` SDK; wiki client uses stdlib `urllib`)

Keep the four modules in the same folder — the server imports the others from its own dir.

## Install into a client

### Recommended: uvx
Needs [uv](https://docs.astral.sh/uv/), pass a save folder/directory with `--save-dir` or just `--save` with the actual save file, which is just the same name as the folder/directory:

`--save-dir` example on Windows with Claude Desktop and proper JSON escapes:
```json
{
  "mcpServers": {
    "sdv-mcp": {
      "command": "uvx",
      "args": [
        "sdv-mcp", // use "sdv-mcp@latest" to always pull the latest version
        "--save-dir", "C:\\Users\\you\\AppData\\Roaming\\StardewValley\\Saves\\FarmName_437005740"
      ]
    }
  }
}
```

`uvx` pulls the package from [PyPI](https://pypi.org/project/sdv-mcp/). Pin a version
with `sdv-mcp==0.1.0`, or install the latest dev build straight from git by adding
`"--from", "git+https://github.com/vehemont/sdv-mcp"` before `"sdv-mcp"`.

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

Runs on stdio. You must point `--save`/`--save-dir` (or the env var) at the save you want; the server reads only that save and never scans your machine for others.

## Disabling tools
By default, all tools are enabled. Any tool you consider cheating/unfair can be turned off so the model never sees it.
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

## Tools (46)

### Save state
| Tool | What |
|------|------|
| `overview` | Date, players, shared money, lifetime earnings, deepest mine, version |
| `players` | Per-player levels, XP, XP-to-next, professions, spouse, backpack, house |
| `community_center` | Rooms done/left, incomplete bundles + exact items needed, Vault status |
| `museum` | Donations / 95 + next milestone (60 = Rusty Key) |
| `monster_goals` | Guild eradication goals: kills vs target + reward |
| `friendships` | Villager hearts/points + spouse, per player |
| `player_tools` | Each player's tools + upgrade tier |
| `wallet` | Keys/special items (Rusty Key, Skull Key, Club Card, ...). 1.5 + 1.6 aware (reads mail flags) |
| `unlocks` | Which gated locations/vendors are reachable (Desert + Desert Trader, Sewers/Krobus, Skull Cavern, Casino, Quarry, Greenhouse, Minecarts, Movie Theater, Guild, Ginger Island) + how to unlock the rest |
| `feed` | Animals, silo hay, fiber, days of feed covered (+ fiber-as-grass-starters) |
| `full_report` | All of the above in one shot |

### Inventory + location
| Tool | What |
|------|------|
| `inventory` | Backpacks + chests. `full=True` = all items; `by_container=True` = per-chest |
| `processing` | Held crops grouped fruit/veg/special by the save's own item category |
| `machines` | Inventory of placed machines (Furnace, Keg, Cask, Seed Maker, Kiln, Tapper, ...) by type with counts + state (ready/working/idle) |
| `chests` | Every container: type (Chest/Stone/Big/special), map + tile, color, contents |
| `find_item` | Where is X? Searches backpacks, chests, machine outputs. Map + tile + color |
| `net_worth` | Gold + sellable value of everything held (from each item's own price) |

### Planning + completion
| Tool | What |
|------|------|
| `quests` | Per-player quest journal + special-orders board (objectives + progress); item quests show requested item, on-hand count, and `completable_now`. `research=True` attaches a wiki `how_to_obtain` summary + infobox for each requested item |
| `can_complete_now` | CC bundles you could finish from what's in your chests right now |
| `bundle_sourcing` | Incomplete bundles + per missing-item wiki how-to-obtain + unlock-aware `locked_source_hints` (flags sources behind gated locations) |
| `missing_museum` | Undonated minerals + artifacts, with where they drop |
| `missing_recipes` | Cooking/crafting recipes learned-but-not-made (+ how many not yet learned), per player |
| `shipping_tracker` | Items shipped by name + qty; distinct count vs the 154 Full-Shipment target |
| `golden_walnuts` | Ginger Island walnut progress: found vs 130, unspent, island-unlock + repeatable sources |
| `perfection` | Real weighted Perfection %: 11 categories, each with have/total + earned %. 1.6-accurate (Farmer Level = player.Level/25) + per-player co-op breakdown |
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

### Wiki verification
| Tool | What |
|------|------|
| `wiki_search` | Search the Stardew Valley Wiki (titles + snippets) |
| `wiki_page` | A page (or one section) as clean text — to verify facts / pull context |
| `wiki_infobox` | A page's infobox as structured fields (price/season/location) |
| `how_to_obtain` | Every way to get an item (drops, shops, trades, gifting) — the wiki lead summary + infobox source. Plan how to get a quest/bundle item |
| `villager_schedule` | A villager's wiki schedule + your save's date/weather/hearts |

## Files
- `sdv_parser.py` — the read-only save parser (ElementTree)
- `sdv_wiki.py` — MediaWiki Action API client (api.php; the wiki's rest.php returns empty, so Action API it is), cached + rate-limited
- `sdv_calc.py` — the calculators + reference tables
- `sdv_mcp_server.py` — the 47 tools

## Known limits
- Vanilla + whatever the wiki documents only. Modded content lives on separate wikis.
- `missing_recipes` lists recipes you've *learned* but not made; recipes not yet learned show only as a count (they aren't in the save). `shipping_tracker` lists what you've shipped by name — a by-name "still to ship" list isn't modelled (the save only stores what shipped), so its remaining count is approximate vs the 154-item set.
- `quests`: `completable_now` covers item delivery/harvest/resource quests (you still hand the item in); monster/fishing/socialize quests report progress counters instead. Special-order item objectives aren't fully modelled. Item ids missing from the local name table show as `#id` — use `research=True` or the wiki tools to identify them.
at- Wiki tools need outbound network. The save tools don't.
