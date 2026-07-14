"""sdv_calc.py - Stardew Valley calculators. Combine SAVE state (via sdv_parser)
with the game's own formulas. Read-only. Values are vanilla and verifiable
against the wiki (sdv_wiki). Where a price/crop isn't in the small built-in
tables, the item is counted for throughput but omitted from gold estimates and
flagged, rather than guessed.
"""
from __future__ import annotations
import math
from collections import Counter
import sdv_parser as P

# ---- reference tables (vanilla) ------------------------------------------
# crop: (seasons, growth_days, regrow_days(0=none), seed_cost, sell_price_base)
CROPS = {
 'Parsnip':({'spring'},4,0,20,35),'Green Bean':({'spring'},10,3,60,40),
 'Cauliflower':({'spring'},12,0,80,175),'Potato':({'spring'},6,0,50,80),
 'Kale':({'spring'},6,0,70,110),'Garlic':({'spring'},4,0,40,60),
 'Rhubarb':({'spring'},13,0,100,220),'Strawberry':({'spring'},8,4,100,120),
 'Tulip':({'spring'},6,0,20,30),'Blue Jazz':({'spring'},7,0,30,50),
 'Blueberry':({'summer'},13,4,80,50),'Melon':({'summer'},12,0,80,250),
 'Hot Pepper':({'summer'},5,3,40,40),'Radish':({'summer'},6,0,40,90),
 'Tomato':({'summer'},11,4,50,60),'Hops':({'summer'},11,1,60,25),
 'Poppy':({'summer'},7,0,100,140),'Starfruit':({'summer'},13,0,400,750),
 'Red Cabbage':({'summer'},9,0,100,260),'Summer Spangle':({'summer'},8,0,50,90),
 'Corn':({'summer','fall'},14,4,150,50),'Wheat':({'summer','fall'},4,0,10,25),
 'Sunflower':({'summer','fall'},8,0,200,80),
 'Pumpkin':({'fall'},13,0,100,320),'Amaranth':({'fall'},7,0,70,150),
 'Grape':({'fall'},10,3,60,80),'Bok Choy':({'fall'},4,0,50,80),
 'Cranberries':({'fall'},7,5,240,75),'Eggplant':({'fall'},5,5,20,60),
 'Yam':({'fall'},10,0,60,160),'Beet':({'fall'},6,0,20,100),
 'Artichoke':({'fall'},8,0,30,160),'Fairy Rose':({'fall'},12,0,200,290),
 'Sweet Gem Berry':({'fall'},24,0,1000,3000),
 'Ancient Fruit':({'greenhouse'},28,7,0,550),
 'Powdermelon':({'winter'},7,0,0,60),
}
# base sell prices for keg/jar value estimates (crops + fruit-tree/foraged fruit)
BASE_PRICE = {name:info[4] for name,info in CROPS.items()}
BASE_PRICE.update({'Blackberry':20,'Wild Plum':80,'Spice Berry':80,'Crystal Fruit':150,
 'Salmonberry':5,'Coconut':100,'Cactus Fruit':75,'Apple':100,'Apricot':50,'Orange':100,
 'Peach':140,'Pomegranate':140,'Cherry':80,'Powdermelon':60,'Qi Fruit':1})
# processing multipliers
KEG = {'fruit_wine':3.0,'veg_juice':2.25}
JAR = {'add':50,'mul':2}
SPECIAL_KEG_VALUE = {'Hops':('Pale Ale',300),'Wheat':('Beer',200),
 'Coffee Bean':('Coffee',150),'Honey':('Mead',200),'Tea Leaves':('Green Tea',100)}
# machine cycle length in days (approx; verifiable vs wiki)
CYCLE_DAYS = {'wine':7,'juice':4,'jelly':3,'pickle':3,'pale ale':2,'beer':2,'mead':1,'coffee':1}
ARTISAN_MULT = 1.4      # Artisan profession (verified vs wiki)
TILLER_MULT = 1.10      # Tiller: +10% crops & foraged goods (raw, not artisan)
RANCHER_MULT = 1.20     # Rancher: +20% animal products (verified vs wiki)
MAX_SKILL_WITH_BUFFS = 14   # food buffs can push a skill to 14 (wiki)

# Food/consumable buffs that raise a SKILL LEVEL (verified vs wiki). These change
# level-dependent effects (e.g. crop quality for farming) but NOT XP gain rate.
BUFFS = {
 "Farmer's Lunch":   {'skill':'farming','amount':3,'duration':'5m35s'},
 "Complete Breakfast":{'skill':'farming','amount':2,'duration':'7m','extra':'+50 Max Energy'},
 "Pepper Poppers":   {'skill':'farming','amount':2,'duration':'7m','extra':'+1 Speed'},
 "Hashbrowns":       {'skill':'farming','amount':1,'duration':'5m35s'},
 "Trout Soup":       {'skill':'fishing','amount':1,'duration':'4m39s'},
 "Dish O' The Sea":  {'skill':'fishing','amount':3,'duration':'button'},
}
FARM_XP = lambda price: round(16*math.log(0.018*price+1))  # farming harvest XP
SEASON_LEN = 28

def _has_profession(root, prof):
    return any(prof in pl['professions'] for pl in P.players(root))

def _player(root, name=None):
    ps = P.players(root)
    if name:
        for p in ps:
            if p['name'].lower() == name.lower(): return p
    return ps[0]

# ---- 1. skill xp forecast -------------------------------------------------
def skill_xp_forecast(root, skill, target_level, player=None,
                      item_price=None, per_action_xp=None, action_label=None):
    """How many actions to reach a target skill level, from current save XP.
    Provide item_price (crop harvest -> farming XP formula) OR per_action_xp
    (e.g. 5 for petting an animal / collecting a product)."""
    skill = skill.lower()
    if not (1 <= target_level <= 10):
        return {'error':'target_level must be 1..10'}
    pl = _player(root, player)
    cur = pl['xp'].get(skill)
    if cur is None:
        return {'error':f"unknown skill '{skill}'", 'skills':list(pl['xp'])}
    target_xp = P.XP_LEVELS[target_level]
    remaining = max(0, target_xp - cur)
    if per_action_xp:
        xp_a = per_action_xp; label = action_label or 'action'
    elif item_price is not None:
        xp_a = FARM_XP(item_price); label = action_label or f'harvest (base {item_price}g)'
    else:
        return {'error':'provide item_price (crop harvest) or per_action_xp'}
    actions = 0 if remaining == 0 else math.ceil(remaining/xp_a)
    return {'player':pl['name'],'skill':skill,'current_level':pl['levels'].get(skill),
            'current_xp':cur,'target_level':target_level,'target_xp':target_xp,
            'xp_remaining':remaining,'xp_per_action':xp_a,'action':label,
            'actions_needed':actions,
            'note':'Farming harvest XP = round(16*ln(0.018*price+1)); animal pet/collect = 5. '
                   'Fishing XP per catch varies by fish; pass per_action_xp for fishing.'}

# ---- 2. processing planner ------------------------------------------------
def processing_planner(root, days=28, extra_kegs=0, extra_jars=0, artisan=None):
    """Given held crops + machines owned, how many kegs/jars to clear the backlog
    in `days`, and an estimated gross value. artisan=None -> auto-detect from any
    player having the Artisan profession."""
    pr = P.processing(root)
    if artisan is None:
        artisan = any('Artisan' in pl['professions'] for pl in P.players(root))
    mult = ARTISAN_MULT if artisan else 1.0
    kegs = pr['kegs_owned'] + extra_kegs
    jars = pr['jars_owned'] + extra_jars

    def cycles(cycle_days):
        return max(0, days // cycle_days)

    fruit_n = sum(pr['fruit'].values()); veg_n = sum(pr['veg'].values())
    spec_n = sum(pr['special_keg'].values())
    keg_items = fruit_n + veg_n + spec_n
    # kegs needed to clear each stream within `days`
    need_wine = math.ceil(fruit_n/cycles('wine' and CYCLE_DAYS['wine'])) if cycles(CYCLE_DAYS['wine']) else None
    need_juice = math.ceil(veg_n/cycles(CYCLE_DAYS['juice'])) if cycles(CYCLE_DAYS['juice']) else None
    kegs_needed = (need_wine or 0)+(need_juice or 0)
    # gross gold estimate (only items with known base price)
    gross = 0; priced = 0; unpriced = Counter()
    for name,q in pr['fruit'].items():
        bp = BASE_PRICE.get(name)
        if bp: gross += q*bp*KEG['fruit_wine']*mult; priced += q
        else: unpriced[name]=q
    for name,q in pr['veg'].items():
        bp = BASE_PRICE.get(name)
        if bp: gross += q*bp*KEG['veg_juice']*mult; priced += q
        else: unpriced[name]=q
    for name,q in pr['special_keg'].items():
        if name in SPECIAL_KEG_VALUE: gross += q*SPECIAL_KEG_VALUE[name][1]*mult; priced += q
        else: unpriced[name]=q
    return {'days':days,'artisan':artisan,
            'kegs_owned':pr['kegs_owned'],'jars_owned':pr['jars_owned'],
            'keg_items_held':keg_items,'fruit':fruit_n,'veg':veg_n,'special':spec_n,
            'cycles_per_keg':{'wine':cycles(CYCLE_DAYS['wine']),'juice':cycles(CYCLE_DAYS['juice'])},
            'kegs_needed_to_clear_in_days':kegs_needed,
            'kegs_to_build':max(0,kegs_needed-kegs),
            'est_gross_gold':round(gross),'items_priced':priced,
            'items_without_price':dict(unpriced),
            'note':'Wine=3x, Juice=2.25x base; Artisan x1.4. Cycle days approximate '
                   '(wine 7, juice 4). Unpriced items are counted for throughput only.'}

# ---- 3. crop planner ------------------------------------------------------
def crop_planner(root, season=None, days_left=None, budget=None, top=12,
                 fertilizer=0, quality_weighted=False):
    """Which crops fully mature in the time left and their profit per tile.
    Defaults season/days_left from the save's current date."""
    ov = P.overview(root)
    season = (season or ov['date']['season'] or '').lower()
    if days_left is None:
        days_left = max(0, SEASON_LEN - ov['date']['day'])
    tiller = _has_profession(root, 'Tiller')
    tmult = TILLER_MULT if tiller else 1.0
    qmult = 1.0
    if quality_weighted:
        fl = max((pl['levels'].get('farming',0) for pl in P.players(root)), default=0)
        q = crop_quality_odds(farming_level=fl, fertilizer=fertilizer)
        qmult = (q['normal_pct']*1.0 + q['silver_pct']*1.25 + q['gold_pct']*1.5
                 + q['iridium_pct']*2.0)/100.0
    rows = []
    for name,(seasons,grow,regrow,seed,base_sell) in CROPS.items():
        sell = round(base_sell*tmult*qmult)
        if season not in seasons and 'greenhouse' not in seasons: continue
        if season not in seasons: continue
        if grow > days_left: continue
        if regrow:
            harvests = 1 + max(0,(days_left-grow)//regrow)
        else:
            harvests = 1
        revenue = harvests*sell
        profit = revenue - seed
        rows.append({'crop':name,'seasons':sorted(seasons),'grow_days':grow,
                     'regrow_days':regrow or None,'seed_cost':seed,'sell_each':sell,
                     'harvests_in_window':harvests,'revenue_per_tile':revenue,
                     'profit_per_tile':profit,'profit_per_day':round(profit/max(1,days_left),1)})
    rows.sort(key=lambda r:-r['profit_per_tile'])
    out = {'season':season,'days_left':days_left,'crops':rows[:top]}
    if not rows:
        out['note_empty'] = ('No standard crops mature in this window. In winter, '
                             'outdoor crops do not grow except Powdermelon (seeds from '
                             'the Raccoon shop / Seed Maker / breaking crates); use the '
                             'greenhouse for year-round growing.')
    if budget is not None and rows:
        best = rows[0]
        aff = budget // best['seed_cost'] if best['seed_cost'] else None
        out['budget'] = budget
        out['best_crop_tiles_affordable'] = {'crop':best['crop'],'tiles':aff,
            'total_profit':(aff*best['profit_per_tile']) if aff else None}
    out['tiller_applied'] = tiller
    out['note'] = ('Prices include Tiller +10% (applied: ' + ('yes' if tiller else 'no') +
                   '). No-star quality; fertilizer and keg processing not included.')
    return out

# ---- 4. friendship / gift forecast ---------------------------------------
def friendship_forecast(root, villager, target_hearts=10, player=None,
                        loved_gifts_per_week=2):
    """Gifts and weeks to reach a target heart level with the villager, from
    current save friendship. Loved gift = +80 pts (x8 on birthday)."""
    fr = P.friendships(root)
    pl = _player(root, player)['name']
    data = fr.get(pl, {})
    cur = next((r['points'] for r in data.get('relationships',[])
                if r['villager'].lower()==villager.lower()), None)
    if cur is None:
        return {'error':f"'{villager}' not found for {pl}",
                'known':[r['villager'] for r in data.get('relationships',[])][:40]}
    target_pts = target_hearts*250
    remaining = max(0, target_pts-cur)
    per_week = loved_gifts_per_week*80
    weeks = 0 if remaining==0 else math.ceil(remaining/per_week)
    loved_gifts_total = 0 if remaining==0 else math.ceil(remaining/80)
    return {'player':pl,'villager':villager,'current_points':cur,
            'current_hearts':cur//250,'target_hearts':target_hearts,
            'points_remaining':remaining,
            'loved_gifts_needed':loved_gifts_total,
            'weeks_at_2_loved_per_week':weeks,
            'note':'Loved gift = +80 (x8 on birthday = +640 once/year). Max 2 gifts/'
                   'villager/week. Non-dating cap is 8 hearts (2000) for datable NPCs; '
                   'talking helps and friendship decays ~2/day if ignored.'}

# ---- 5. sprinkler coverage & cost ----------------------------------------
SPRINKLERS = {
 'Basic':  {'coverage':4,  'materials':{'Copper Bar':1,'Iron Bar':1}},
 'Quality':{'coverage':8,  'materials':{'Iron Bar':1,'Gold Bar':1,'Refined Quartz':1}},
 'Iridium':{'coverage':24, 'materials':{'Gold Bar':1,'Iridium Bar':1,'Battery Pack':1}},
}
def sprinkler_plan(root, tiles, sprinkler='Quality'):
    """Sprinklers + materials to water `tiles`, and whether the save can build them."""
    sprinkler = sprinkler.capitalize()
    if sprinkler not in SPRINKLERS:
        return {'error':'sprinkler must be Basic, Quality, or Iridium'}
    spec = SPRINKLERS[sprinkler]; count = math.ceil(tiles/spec['coverage'])
    need = {m:q*count for m,q in spec['materials'].items()}
    held = P._combined_inventory(root)
    buildable = min((held.get(m,0)//q for m,q in spec['materials'].items()), default=0)
    shortfall = {m:max(0, need[m]-held.get(m,0)) for m in need}
    return {'sprinkler':sprinkler,'tiles':tiles,'coverage_each':spec['coverage'],
            'sprinklers_needed':count,'materials_needed':need,
            'materials_on_hand':{m:held.get(m,0) for m in need},
            'buildable_now':buildable,'shortfall':{m:v for m,v in shortfall.items() if v},
            'note':'Coverage: Basic 4 (adjacent), Quality 8 (surrounding), Iridium 24 (5x5). '
                   'Pressure Nozzle doubles coverage. Bars require ore + coal in a furnace.'}

# ---- 6. processing value comparison --------------------------------------
def processing_value(root, item, base_price=None, kind=None, quality='normal', artisan=None):
    """Rank ways to sell one crop: raw (at quality) vs keg (wine/juice) vs jar
    (jelly/pickle). kind 'fruit'/'veg' auto-detected from the save's category."""
    if base_price is None:
        base_price = BASE_PRICE.get(item)
    if base_price is None:
        return {'error':f"no base price known for '{item}'; pass base_price"}
    if kind is None:
        meta = P._object_meta(root).get(item, {})
        cat = meta.get('category')
        kind = 'fruit' if cat == -79 else ('veg' if cat == -75 else None)
    if artisan is None:
        artisan = any('Artisan' in pl['professions'] for pl in P.players(root))
    amult = ARTISAN_MULT if artisan else 1.0
    tiller = _has_profession(root, 'Tiller')
    tmult = TILLER_MULT if tiller else 1.0
    qmult = {'normal':1.0,'silver':1.25,'gold':1.5,'iridium':2.0}.get(quality,1.0)
    # Tiller (+10%) applies to RAW crops/forage, not to artisan goods
    options = {'raw ('+quality+')': round(base_price*qmult*tmult)}
    if kind == 'fruit':
        options['wine'] = round(base_price*KEG['fruit_wine']*amult)
    elif kind == 'veg':
        options['juice'] = round(base_price*KEG['veg_juice']*amult)
    options['jelly/pickle'] = round((base_price*JAR['mul']+JAR['add'])*amult)
    best = max(options, key=options.get)
    return {'item':item,'base_price':base_price,'kind':kind or 'unknown',
            'artisan':artisan,'tiller':tiller,
            'quality_for_raw':quality,'values':dict(sorted(options.items(), key=lambda x:-x[1])),
            'best':best,'best_value':options[best],
            'note':'Wine 3x, Juice 2.25x, Jelly/Pickle 2x+50 (base). Artisan x1.4 (artisan '
                   'goods ignore input quality). Raw scales with star quality. Aging in a cask '
                   'can raise wine/cheese quality further.'}

# ---- 7. fish pond forecast -----------------------------------------------
POND_SPAWN_DAYS = {'Sturgeon':4,'Lava Eel':5,'Ice Pip':5,'Slimejack':1,'Rainbow Trout':2,
 'Blobfish':3,'Void Salmon':2,'Stonefish':3,'default':2}
def fish_pond_forecast(root, fish=None, current_pop=None, capacity=10, spawn_days=None):
    """Days to fill a fish pond to capacity via reproduction. Reads existing ponds
    from the save; or pass fish/current_pop/capacity to model a hypothetical one."""
    ponds = []
    for b in root.iter('Building'):
        bt = b.find('buildingType')
        if bt is not None and bt.text == 'Fish Pond':
            ft = b.find('fishType'); occ = b.find('currentOccupants'); mx = b.find('maxOccupants')
            ponds.append({'fish': ft.text if ft is not None else None,
                          'population': int(occ.text) if occ is not None and occ.text else None,
                          'capacity': int(mx.text) if mx is not None and mx.text else 10})
    def forecast(fname, pop, cap):
        interval = spawn_days or POND_SPAWN_DAYS.get(fname, POND_SPAWN_DAYS['default'])
        need = max(0, cap - (pop or 0))
        return {'fish':fname,'population':pop,'capacity':cap,'spawn_interval_days':interval,
                'to_fill':need,'days_to_fill_est':need*interval}
    if fish:
        return {'from':'parameters','forecast':forecast(fish, current_pop, capacity)}
    if ponds:
        return {'from':'save','ponds':[forecast(p['fish'],p['population'],p['capacity']) for p in ponds],
                'note':'Capacity starts at 1 and rises to 3/5/7/10 via pond quests. Roe output '
                       'chance rises with population; Sturgeon/other roe -> Preserves Jar = Caviar.'}
    return {'from':'save','ponds':[],'note':'No fish ponds found. Pass fish/current_pop/capacity '
            'to model one (e.g. a Sturgeon pond for Caviar).'}

# ---- 8. crop quality odds -------------------------------------------------
def crop_quality_odds(farming_level=None, fertilizer=0, food_buff=0, root=None, player=None):
    """Gold/silver/normal (and iridium w/ Deluxe) quality probabilities using the
    game's formula. fertilizer: 0 none, 1 Basic, 2 Quality, 3 Deluxe."""
    if farming_level is None:
        if root is None:
            return {'error':'pass farming_level or a save (root)'}
        farming_level = _player(root, player)['levels'].get('farming', 0)
    base_fl = int(farming_level); fert = int(fertilizer)
    fl = min(MAX_SKILL_WITH_BUFFS, base_fl + int(food_buff))   # food buffs raise effective level (max 14)
    num = 0.2*(fl/10.0) + 0.2*fert*((fl+2)/12.0) + 0.01
    clamp = lambda x: max(0.0, min(1.0, x))
    irid_thr = (num/2) if fert >= 3 else 0.0      # cutoffs checked in order: iridium, gold, silver
    gold_thr = num
    silver_thr = min(0.75, num*2)
    p_irid   = clamp(irid_thr)
    p_gold   = max(0.0, clamp(gold_thr)   - clamp(irid_thr))
    p_silver = max(0.0, clamp(silver_thr) - clamp(gold_thr))
    p_normal = 1.0 - clamp(max(gold_thr, silver_thr))
    pct = lambda x: round(100*x, 1)
    return {'base_farming_level':base_fl,'food_buff':int(food_buff),
            'effective_farming_level':fl,'fertilizer_level':fert,
            'iridium_pct':pct(p_irid),'gold_pct':pct(p_gold),
            'silver_pct':pct(p_silver),'normal_pct':pct(p_normal),
            'note':'Iridium only with Deluxe Fertilizer (lvl 3). Food buffs raise the effective '
                   'farming level (e.g. Farmer\'s Lunch +3), capped at 14. Formula: '
                   'num = 0.2*(lvl/10) + 0.2*fert*((lvl+2)/12) + 0.01.'}


def list_buffs(skill=None):
    """Food/consumable buffs that raise a skill LEVEL (verified vs wiki). Note:
    these change level-dependent effects (crop quality, fishing ability) but do
    NOT increase XP gain rate. Qi Seasoning increases a dish's buff further."""
    items = [{'food':k, **v} for k,v in BUFFS.items() if (skill is None or v['skill']==skill)]
    items.sort(key=lambda x:(-x['amount']))
    return {'buffs':items,'max_effective_skill_level':MAX_SKILL_WITH_BUFFS,
            'note':'Skill-level buffs affect abilities (e.g. crop quality via farming level, '
                   'fishing bite/treasure via fishing level) but NOT XP per action. '
                   'Qi Seasoning raises the buff amount.'}

# ======================= animal + fishing + quality-weighting =============
COOP_ANIMALS = {'White Chicken','Brown Chicken','Blue Chicken','Void Chicken','Golden Chicken',
                'Duck','Rabbit','Dinosaur'}
BARN_ANIMALS = {'White Cow','Brown Cow','Cow','Goat','Sheep','Pig','Ostrich'}
ANIMAL_PRODUCT_PRICE = {'Milk':125,'Large Milk':190,'Egg':50,'Large Egg':95,'Duck Egg':95,
 'Wool':340,'Goat Milk':225,'L. Goat Milk':345,'Large Goat Milk':345,'Truffle':625,
 'Duck Feather':250,"Rabbit's Foot":565,'Void Egg':65,'Dinosaur Egg':350,'Ostrich Egg':600}
# raw product -> (artisan good, base price)   [verified: Cheese 230, Mayonnaise 190]
PRODUCT_TO_ARTISAN = {'Milk':('Cheese',230),'Large Milk':('Cheese',230),
 'Goat Milk':('Goat Cheese',400),'L. Goat Milk':('Goat Cheese',400),
 'Egg':('Mayonnaise',190),'Large Egg':('Mayonnaise',190),'Duck Egg':('Duck Mayonnaise',375),
 'Void Egg':('Void Mayonnaise',275),'Wool':('Cloth',470),'Truffle':('Truffle Oil',1065)}
Q_MULT = {'normal':1.0,'silver':1.25,'gold':1.5,'iridium':2.0}
# fishing difficulty (from Fish.xnb; common fish - extend as needed)
FISH_DIFFICULTY = {'Sardine':30,'Anchovy':30,'Herring':30,'Tuna':70,'Sturgeon':78,'Catfish':75,
 'Pufferfish':80,'Sandfish':65,'Tilapia':50,'Walleye':45,'Eel':70,'Red Snapper':40,
 'Tiger Trout':60,'Ghostfish':50,'Woodskip':50,'Squid':75,'Lingcod':85,'Midnight Carp':55,
 'Rainbow Trout':45,'Salmon':50,'Largemouth Bass':50,'Bream':35,'Carp':15,'Chub':35,
 'Blobfish':75,'Crimsonfish':95,'Glacierfish':100,'Legend':110,'Angler':85,'Mutant Carp':80}

def animal_product_quality(root=None, friendship=None, mood=None, animal_type=None,
                           profession_bonus=False):
    """Iridium/gold/silver/normal produce odds. With a save, reports each animal;
    or pass friendship (0-1000), mood (0-255), animal_type, profession_bonus."""
    def odds(fr, md, prof):
        score = (fr/1000.0) - (1 - md/225.0) + (0.333 if prof else 0.0)
        g = max(0.0, min(1.0, score/2.0)); s = max(0.0, min(1.0, score))
        if score > 0.95:
            pI, pG, pS = g, (1-g)*g, (1-g)*(1-g)*s
        else:
            pI, pG, pS = 0.0, g, (1-g)*s
        pN = max(0.0, 1 - (pI+pG+pS))
        pct = lambda x: round(100*x, 1)
        avg_price_mult = pI*2.0 + pG*1.5 + pS*1.25 + pN*1.0
        return {'score':round(score,3),'iridium_pct':pct(pI),'gold_pct':pct(pG),
                'silver_pct':pct(pS),'normal_pct':pct(pN),
                'avg_value_multiplier':round(avg_price_mult,3)}
    if friendship is not None:
        return {'from':'parameters','animal_type':animal_type,
                'result':odds(friendship, mood if mood is not None else 255, profession_bonus)}
    if root is None:
        return {'error':'pass a save (root) or friendship/mood'}
    def _num(el):
        """Parse an XML element's int text, tolerating missing/empty/nil/float values."""
        if el is None or el.text is None:
            return None
        try:
            return int(float(el.text.strip()))
        except (ValueError, AttributeError):
            return None
    has_coop = _has_profession(root,'Coopmaster'); has_shep = _has_profession(root,'Shepherd')
    out = []
    for a in P.farm_animals(root):
        t = a.find('type'); fr = a.find('friendshipTowardFarmer'); md = a.find('happiness')
        nm = a.find('name')
        atype = t.text if t is not None else None
        fr_v = _num(fr); md_v = _num(md)
        prof = (has_coop and atype in COOP_ANIMALS) or (has_shep and atype in BARN_ANIMALS)
        out.append({'name':nm.text if nm is not None else None,'type':atype,
                    'friendship':fr_v,
                    'mood':md_v,
                    'profession_bonus':prof,
                    **odds(fr_v if fr_v is not None else 0,
                           md_v if md_v is not None else 0, prof)})
    return {'from':'save','animals':out,
            'note':'score = friendship/1000 - (1 - mood/225) + 0.333 (Coopmaster/Shepherd). '
                   'Iridium only if score > 0.95. Verified vs wiki.'}

def animal_product_value(root, product, quality='normal', rancher=None, artisan=None):
    """Raw (Rancher +20% + quality) vs processed (Artisan +40%) value for an animal product."""
    base = ANIMAL_PRODUCT_PRICE.get(product)
    if base is None:
        return {'error':f"no price for '{product}'",'known':sorted(ANIMAL_PRODUCT_PRICE)}
    if rancher is None: rancher = _has_profession(root,'Rancher')
    if artisan is None: artisan = _has_profession(root,'Artisan')
    rmult = RANCHER_MULT if rancher else 1.0
    qmult = Q_MULT.get(quality,1.0)
    values = {f'raw ({quality})': round(base*qmult*rmult)}
    if product in PRODUCT_TO_ARTISAN:
        good, gbase = PRODUCT_TO_ARTISAN[product]
        values[good] = round(gbase*(ARTISAN_MULT if artisan else 1.0))
    best = max(values, key=values.get)
    return {'product':product,'base_price':base,'rancher':rancher,'artisan':artisan,
            'values':dict(sorted(values.items(), key=lambda x:-x[1])),'best':best,
            'note':'Rancher +20% applies to raw animal products (not artisan goods). '
                   'Artisan +40% applies to Cheese/Mayo/Cloth/etc. Large Milk/Egg auto-make '
                   'gold-quality Cheese/Mayo.'}

def fishing_xp_forecast(root, target_level, difficulty=None, fish=None, quality='normal',
                        perfect=False, treasure=False, legendary=False, player=None):
    """Catches needed to reach a target fishing level. XP = ((quality+1)*3) + (difficulty/3),
    x2.2 treasure, x2.4 perfect, x5 legendary (truncated each step). Verified vs wiki."""
    if not (1 <= target_level <= 10):
        return {'error':'target_level must be 1..10'}
    if difficulty is None and fish:
        difficulty = FISH_DIFFICULTY.get(fish)
    if difficulty is None:
        return {'error':'pass difficulty (5-110) or a known fish',
                'known_fish':sorted(FISH_DIFFICULTY)}
    qv = {'normal':0,'silver':1,'gold':2,'iridium':4}.get(quality,0)
    xp = int(((qv+1)*3) + (difficulty/3.0))
    for mult in ([2.2] if treasure else []) + ([2.4] if perfect else []) + ([5] if legendary else []):
        xp = int(xp*mult)
    pl = _player(root, player); cur = pl['xp'].get('fishing',0)
    target_xp = P.XP_LEVELS[target_level]; remaining = max(0, target_xp-cur)
    catches = 0 if remaining==0 else math.ceil(remaining/xp) if xp else None
    return {'player':pl['name'],'current_fishing_level':pl['levels'].get('fishing'),
            'current_xp':cur,'target_level':target_level,'target_xp':target_xp,
            'xp_remaining':remaining,'fish':fish,'difficulty':difficulty,'quality':quality,
            'perfect':perfect,'treasure':treasure,'legendary':legendary,
            'xp_per_catch':xp,'catches_needed':catches,
            'note':'Non-fish items = 3 XP, crab pots = 5 XP each. Perfect catch upgrades the '
                   'displayed quality but XP uses the original quality.'}
