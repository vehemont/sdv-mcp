"""sdv_parser.py - Read-only Stardew Valley save parser (game 1.5/1.6).

Robust ElementTree-based parser that works on ANY save (host + all farmhands,
any names). Every function returns plain JSON-serialisable dicts/lists so a
caller (CLI or MCP server) can present facts and make its own recommendations.

The parser NEVER writes to the save.
"""
from __future__ import annotations
import os, glob, xml.etree.ElementTree as ET
from collections import Counter

XSI = '{http://www.w3.org/2001/XMLSchema-instance}type'

# ---- reference data -------------------------------------------------------
PROF = {0:'Rancher',1:'Tiller',2:'Coopmaster',3:'Shepherd',4:'Artisan',5:'Agriculturist',
        6:'Fisher',7:'Trapper',8:'Angler',9:'Pirate',10:'Mariner',11:'Luremaster',
        12:'Forester',13:'Gatherer',14:'Lumberjack',15:'Tapper',16:'Botanist',17:'Tracker',
        18:'Miner',19:'Geologist',20:'Blacksmith',21:'Prospector',22:'Excavator',23:'Gemologist',
        24:'Fighter',25:'Scout',26:'Brute',27:'Defender',28:'Acrobat',29:'Desperado'}
XP_LEVELS = [0,100,380,770,1300,2150,3300,4800,6900,10000,15000]
SKILL_ORDER = ['farming','fishing','foraging','mining','combat','luck']

KEG_FRUIT = {'Ancient Fruit','Grape','Cranberries','Blueberry','Melon','Starfruit','Rhubarb',
 'Strawberry','Apple','Apricot','Orange','Peach','Pomegranate','Cherry','Banana','Mango',
 'Hot Pepper','Blackberry','Wild Plum','Salmonberry','Spice Berry','Crystal Fruit','Powdermelon',
 'Cactus Fruit','Coconut','Qi Fruit'}
KEG_VEG = {'Parsnip','Green Bean','Cauliflower','Potato','Garlic','Kale','Tomato','Radish',
 'Red Cabbage','Corn','Eggplant','Artichoke','Pumpkin','Bok Choy','Yam','Beet','Amaranth',
 'Broccoli','Carrot','Summer Squash','Unmilled Rice'}
SPECIAL_KEG = {'Hops':'Pale Ale','Wheat':'Beer','Coffee Bean':'Coffee','Honey':'Mead','Tea Leaves':'Green Tea'}
ANIMAL_INPUT = {'Milk','Large Milk','Goat Milk','L. Goat Milk','Egg','Large Egg','Duck Egg',
 'Void Egg','Dinosaur Egg','Wool','Truffle'}

GOALS = [
 ("Slimes",1000,{'Green Slime','Frost Jelly','Sludge','Tiger Slime','Blue Slime','Red Sludge',
   'Purple Slime','Yellow Slime','Big Slime','Metal Head'},"Bug Steak recipe"),
 ("Void Spirits",150,{'Shadow Brute','Shadow Shaman','Shadow Sniper'},"Warrior Ring"),
 ("Bats",200,{'Bat','Frost Bat','Lava Bat','Iridium Bat'},"-"),
 ("Skeletons",50,{'Skeleton','Skeleton Mage'},"-"),
 ("Cave Insects",125,{'Bug','Fly','Grub'},"-"),
 ("Duggies",30,{'Duggy'},"-"),
 ("Dust Sprites",500,{'Dust Spirit'},"Burglar's Ring"),
 ("Rock Crabs",60,{'Rock Crab','Lava Crab','Iridium Crab'},"-"),
 ("Mummies",100,{'Mummy'},"-"),
 ("Pepper Rex",50,{'Pepper Rex'},"-"),
 ("Serpents",250,{'Serpent','Royal Serpent'},"-"),
 ("Magma Sprites",150,{'Magma Sprite','Magma Sparker'},"-"),
]
MUSEUM_TOTAL = 95
MUSEUM_MILESTONES = {11:'Ancient Seeds recipe',40:'Reward',50:'Reward',60:'Rusty Key (Sewers)',
 70:'Reward',80:'Reward',90:'Reward',95:'Complete (Stardrop)'}

# id -> name for CC bundle item slots (vanilla + common)
ITEM = {'24':'Parsnip','16':'Wild Horseradish','18':'Daffodil','20':'Leek','22':'Dandelion',
 '78':'Cave Carrot','88':'Coconut','90':'Cactus Fruit','188':'Green Bean','190':'Cauliflower',
 '192':'Potato','248':'Garlic','250':'Kale','252':'Rhubarb','254':'Melon','256':'Tomato',
 '257':'Morel','258':'Blueberry','259':'Fiddlehead Fern','260':'Hot Pepper','262':'Wheat',
 '264':'Radish','266':'Red Cabbage','268':'Starfruit','270':'Corn','272':'Eggplant',
 '274':'Artichoke','276':'Pumpkin','278':'Bok Choy','280':'Yam','281':'Chanterelle',
 '282':'Cranberries','284':'Beet','300':'Amaranth','304':'Hops','388':'Wood','390':'Stone',
 '392':'Nautilus Shell','396':'Spice Berry','397':'Sea Urchin','398':'Grape','400':'Strawberry',
 '402':'Sweet Pea','404':'Common Mushroom','406':'Wild Plum','408':'Hazelnut','410':'Blackberry',
 '412':'Winter Root','414':'Crystal Fruit','416':'Snow Yam','418':'Crocus','420':'Red Mushroom',
 '421':'Sunflower','422':'Purple Mushroom','62':'Aquamarine','709':'Hardwood','724':'Maple Syrup',
 '725':'Oak Resin','726':'Pine Tar','174':'Large Egg(W)','176':'Egg','180':'Egg(B)',
 '182':'Large Egg(B)','184':'Milk','186':'Large Milk','436':'Goat Milk','438':'L. Goat Milk',
 '440':'Wool','442':'Duck Egg','444':'Duck Feather','446':"Rabbit's Foot",'303':'Pale Ale',
 '306':'Mayonnaise','307':'Duck Mayo','308':'Void Mayo','340':'Honey','342':'Pickles',
 '344':'Jelly','346':'Beer','348':'Wine','350':'Juice','424':'Cheese','426':'Goat Cheese',
 '428':'Cloth','432':'Truffle Oil','430':'Truffle','459':'Mead','178':'Hay','194':'Fried Egg',
 '228':'Maki Roll','651':'Poppyseed Muffin','613':'Apple','634':'Apricot','635':'Orange',
 '636':'Peach','637':'Pomegranate','638':'Cherry','372':'Clam','718':'Cockle','702':'Chub',
 '536':'Frozen Geode','128':'Pufferfish','130':'Tuna','131':'Sardine','132':'Bream',
 '136':'Largemouth Bass','140':'Walleye','142':'Carp','143':'Catfish','145':'Sunfish',
 '148':'Eel','150':'Red Snapper','156':'Ghostfish','164':'Sandfish','698':'Sturgeon',
 '699':'Tiger Trout','700':'Bullhead','701':'Tilapia','706':'Shad','734':'Woodskip'}

# fish -> (seasons, weathers, locations, (start_hr,end_hr))  weather: any/sunny/rain
FISH = {
 'Catfish':({'spring','summer','fall'},{'rain'},{'river','secret woods'},(6,24)),
 'Tiger Trout':({'fall','winter'},{'any'},{'river'},(6,19)),
 'Sturgeon':({'summer','winter'},{'any'},{'mountain lake'},(6,19)),
 'Tuna':({'summer','winter'},{'any'},{'ocean'},(6,19)),
 'Red Snapper':({'summer','fall','winter'},{'rain'},{'ocean'},(6,19)),
 'Tilapia':({'summer','fall'},{'any'},{'ocean'},(6,14)),
 'Walleye':({'fall','winter'},{'rain'},{'river','mountain lake'},(12,26)),
 'Eel':({'spring','fall'},{'rain'},{'ocean'},(16,26)),
 'Pufferfish':({'summer'},{'sunny'},{'ocean'},(12,16)),
 'Sandfish':({'spring','summer','fall','winter'},{'any'},{'desert'},(6,20)),
 'Ghostfish':({'spring','summer','fall','winter'},{'any'},{'mines'},(6,26)),
 'Woodskip':({'spring','summer','fall','winter'},{'any'},{'secret woods'},(6,26)),
 'Midnight Carp':({'fall','winter'},{'any'},{'mountain lake','forest pond'},(22,26)),
 'Lingcod':({'winter'},{'any'},{'river','mountain lake'},(6,26)),
 'Squid':({'winter'},{'any'},{'ocean'},(18,26)),
 'Albacore':({'fall','winter'},{'any'},{'ocean'},(6,11)),
 'Sardine':({'spring','fall','winter'},{'any'},{'ocean'},(6,19)),
}

# ---- loading --------------------------------------------------------------
_CACHE = {}
def load_save(path):
    """Parse a save file into an ElementTree root. Cached by (path, mtime).
    Handles the UTF-8 BOM and trailing null padding Stardew writes."""
    mtime = os.path.getmtime(path)
    key = (os.path.abspath(path), mtime)
    if key in _CACHE:
        return _CACHE[key]
    data = open(path, 'rb').read()
    end = data.rfind(b'</SaveGame>')
    if end != -1:
        data = data[:end + len(b'</SaveGame>')]
    root = ET.fromstring(data)
    _CACHE.clear(); _CACHE[key] = root
    return root

def find_saves():
    """Locate Stardew save folders across common OS locations. Returns list of
    {farm, path} where path is the main save file."""
    roots = []
    ad = os.environ.get('APPDATA')
    if ad: roots.append(os.path.join(ad, 'StardewValley', 'Saves'))
    home = os.path.expanduser('~')
    roots += [os.path.join(home, '.config', 'StardewValley', 'Saves'),
              os.path.join(home, 'Library', 'Application Support', 'StardewValley', 'Saves')]
    # Steam Proton (Linux)
    roots += glob.glob(os.path.join(home, '.steam', 'steam', 'steamapps', 'compatdata',
                                    '413150', 'pfx', 'drive_c', 'users', '*', 'AppData',
                                    'Roaming', 'StardewValley', 'Saves'))
    out = []
    for r in roots:
        if not os.path.isdir(r): continue
        for farm in os.listdir(r):
            main = os.path.join(r, farm, farm)
            if os.path.isfile(main):
                out.append({'farm': farm, 'path': main})
    return out

# ---- helpers --------------------------------------------------------------
def _t(el, tag, default=None):
    c = el.find(tag) if el is not None else None
    return c.text if c is not None and c.text is not None else default

def _players(root):
    ps = []
    host = root.find('player')
    if host is not None: ps.append(host)
    ps += root.findall('farmhands/Farmer')
    if not ps:  # fallback for odd layouts
        ps = list(root.iter('Farmer'))
    return ps

def _items_in(el):
    """Counter of name->qty for the direct <items> child of an element."""
    c = Counter()
    items = el.find('items')
    if items is None: return c
    for it in items.findall('Item'):
        nm = it.find('name')
        if nm is None or nm.text is None: continue  # empty slot
        st = it.find('stack')
        c[nm.text] += int(st.text) if st is not None and st.text else 1
    return c

def _all_chest_contents(root):
    total = Counter(); n = 0
    for obj in root.iter('Object'):
        if obj.get(XSI) == 'Chest':
            n += 1
            total += _items_in(obj)   # direct items only; nested chests counted on their own pass
    return total, n

def _mail(root):
    m = list(root.iter('mailReceived'))
    return {s.text for s in m[0].findall('string')} if m else set()

# ---- section builders (all return plain dicts/lists) ----------------------
def overview(root):
    host = root.find('player')
    return {
        'farm_name': _t(host, 'farmName'),
        'host': _t(host, 'name'),
        'players': [ _t(p,'name') for p in _players(root) ],
        'date': {'day': int(_t(root,'dayOfMonth',0)), 'season': _t(root,'currentSeason'),
                 'year': int(_t(root,'year',0))},
        'money_shared': int(_t(host,'money',0)),
        'total_earned': int(_t(host,'totalMoneyEarned',0)),
        'deepest_mine_level': int(_t(host,'deepestMineLevel',0)),
        'game_version': _t(root,'gameVersion'),
    }

def players(root):
    out = []
    for p in _players(root):
        lv = {s: int(_t(p, s+'Level', 0)) for s in
              ['farming','fishing','foraging','mining','combat','luck']}
        xp_el = p.find('experiencePoints')
        xp = [int(x.text) for x in xp_el.findall('int')] if xp_el is not None else []
        xp_map = dict(zip(SKILL_ORDER, xp)) if xp else {}
        to_next = {}
        for sk in ['farming','fishing','foraging','mining','combat']:
            if sk in xp_map:
                x = xp_map[sk]; nxt = next((L for L in XP_LEVELS if L > x), None)
                if nxt: to_next[sk] = nxt - x
        prof_el = p.find('professions')
        profs = [PROF.get(int(i.text), i.text) for i in prof_el.findall('int')] if prof_el is not None else []
        out.append({'name': _t(p,'name'), 'levels': lv, 'xp': xp_map,
                    'xp_to_next_level': to_next, 'professions': profs,
                    'spouse': _t(p,'spouse') or None,
                    'backpack_slots': int(_t(p,'maxItems',0)),
                    'house_upgrade': int(_t(p,'houseUpgradeLevel',0))})
    return out

def community_center(root):
    mail = _mail(root)
    rooms = {'ccBoilerRoom':'BoilerRoom','ccCraftsRoom':'CraftsRoom','ccPantry':'Pantry',
             'ccFishTank':'FishTank','ccVault':'Vault','ccBulletin':'Bulletin'}
    done = [v for k,v in rooms.items() if k in mail]
    left = [v for k,v in rooms.items() if k not in mail]
    # bundle definitions
    meta = {}
    bd = next(iter(root.iter('bundleData')), None)
    if bd is not None:
        for item in bd.findall('item'):
            k = item.find('key/string').text; v = item.find('value/string').text
            room = k.split('/')[0]; bid = int(k.split('/')[1]); parts = v.split('/')
            ids = parts[2].split()[0::3] if parts[2].strip() else []
            nreq = parts[4] if len(parts) > 4 and parts[4].strip() else str(len(ids))
            meta[bid] = (room, parts[0], ids, int(nreq) if nreq.isdigit() else len(ids))
    prog = {}
    bn = next(iter(root.iter('bundles')), None)
    if bn is not None:
        for item in bn.findall('item'):
            bid = int(item.find('key/int').text)
            prog[bid] = [b.text == 'true' for b in item.findall('value/ArrayOfBoolean/boolean')]
    incomplete = []
    for bid,(room,name,ids,nreq) in sorted(meta.items()):
        if room in ('Vault','Abandoned Joja Mart'): continue
        b = prog.get(bid, [])
        got = sum(1 for i in range(min(len(ids),len(b))) if b[i])
        if got < nreq:
            need = [ITEM.get(ids[i], '#'+ids[i]) for i in range(min(len(ids),len(b))) if not b[i]]
            incomplete.append({'room':room,'bundle':name,'need_count':nreq-got,
                               'of':nreq,'items_remaining':need})
    vault = {}
    for bid,label in {23:'2,500g',24:'5,000g',25:'10,000g',26:'25,000g'}.items():
        b = prog.get(bid, [False])
        vault[label] = 'paid' if any(b) else 'unpaid'
    return {'rooms_done':done,'rooms_left':left,'incomplete_bundles':incomplete,'vault':vault}

def inventory(root, full=False, by_container=False):
    per = {}
    for p in _players(root):
        c = _items_in(p)
        per[_t(p,'name')] = dict(c.most_common())
    storage, nch = _all_chest_contents(root)
    out = {'backpacks':per,'chest_count':nch}
    if by_container:
        # per-container breakdown (type, location, tile, color, contents)
        out['containers'] = chests(root)['chests']
        out['note'] = 'by_container=True: chest contents listed per container instead of merged.'
    else:
        chest = storage.most_common() if full else storage.most_common(40)
        out['chests_combined'] = dict(chest)
        out['chests_total_types'] = len(storage)
        out['chests_total_items'] = sum(storage.values())
    return out

def _combined_inventory(root):
    total = Counter()
    for p in _players(root): total += _items_in(p)
    st,_ = _all_chest_contents(root); total += st
    return total

FRUIT_CATEGORY = -79
VEG_CATEGORY = -75

def _is_vanilla_id(iid):
    """Vanilla item ids are numeric ('282') or simple tokens ('Carrot',
    'SteelPickaxe'). Modded content uses a namespaced id containing '.' or '/'
    (e.g. 'Author.Mod_Item'). Vanilla ids never contain those, so that's the
    discriminator."""
    if not iid:
        return True
    core = iid.split(')')[-1] if ')' in iid else iid   # drop (O)/(BC) qualifier
    return ('.' not in core) and ('/' not in core)

def _object_meta(root):
    """name -> {category:int|None, id:str|None, vanilla:bool} for every object/item
    encountered (placed <Object> and carried <Item>). First occurrence wins."""
    meta = {}
    for el in list(root.iter('Object')) + list(root.iter('Item')):
        nm = el.find('name')
        if nm is None or nm.text is None or nm.text in meta:
            continue
        cat = el.find('category'); iid = el.find('itemId')
        catv = (int(cat.text) if cat is not None and cat.text is not None
                and cat.text.lstrip('-').isdigit() else None)
        idv = iid.text if iid is not None else None
        meta[nm.text] = {'category': catv, 'id': idv, 'vanilla': _is_vanilla_id(idv)}
    return meta

def processing(root):
    """Keg/jar planning. Classification is DATA-DRIVEN from each item's own
    <category> field in the save (-79 Fruit, -75 Vegetable), so it needs no
    hardcoded crop lists. Modded items (non-vanilla ids) are EXCLUDED from the
    vanilla buckets and reported separately so totals stay trustworthy."""
    total = _combined_inventory(root)
    meta = _object_meta(root)
    fruit = {}; veg = {}; spec = {}; anim = {}; modded = {}
    for name, qty in total.items():
        m = meta.get(name, {})
        cat = m.get('category')
        keg_relevant = (name in SPECIAL_KEG) or cat in (FRUIT_CATEGORY, VEG_CATEGORY)
        if not m.get('vanilla', True):
            if keg_relevant:
                modded[name] = qty                  # modded crop -> set aside, flagged
            continue
        if name in SPECIAL_KEG:
            spec[name] = qty
        elif cat == FRUIT_CATEGORY:
            fruit[name] = qty
        elif cat == VEG_CATEGORY:
            veg[name] = qty
        if name in ANIMAL_INPUT:
            anim[name] = qty
    kegs = sum(1 for o in root.iter('Object') if _t(o,'name')=='Keg')
    jars = sum(1 for o in root.iter('Object') if _t(o,'name')=='Preserves Jar')
    return {'classification': "by save's own item <category> field (data-driven): "
                              "-79 Fruit, -75 Vegetable; special keg items by name",
            'fruit':fruit,'fruit_total':sum(fruit.values()),
            'veg':veg,'veg_total':sum(veg.values()),
            'special_keg':spec,'special_total':sum(spec.values()),
            'animal_inputs':anim,
            'keg_able_total':sum(fruit.values())+sum(veg.values())+sum(spec.values()),
            'kegs_owned':kegs,'jars_owned':jars,
            'mods_detected':bool(modded),
            'modded_items_excluded':modded,
            'modded_note': ("Excluded modded crops from keg-able totals (their game "
                            "rules aren't in the save). Their names/quantities are "
                            "listed above.") if modded else None}

def feed(root):
    animals = Counter(a.find('type').text for a in root.iter('FarmAnimal') if a.find('type') is not None)
    n = sum(animals.values())
    silo = sum(int(e.text) for e in root.iter('piecesOfHay'))
    fiber = _combined_inventory(root).get('Fiber',0)
    season = _t(root,'currentSeason')
    hay_from_fiber = fiber // 2   # 1 fiber -> 1 grass starter -> ~0.5 hay (basic scythe)
    res = {'animals':dict(animals),'animal_count':n,'silo_hay':silo,'fiber':fiber,
           'season':season,'days_covered_silo': (silo//n) if n else None}
    if n:
        res['hay_from_fiber_est'] = hay_from_fiber
        res['days_covered_with_fiber_winter'] = (silo+hay_from_fiber)//n
        res['grass_regrows'] = season != 'winter'
    return res

def museum(root):
    mp = next(iter(root.iter('museumPieces')), None)
    donated = len(mp.findall('item')) if mp is not None else 0
    nxt = next((k for k in sorted(MUSEUM_MILESTONES) if k > donated), None)
    return {'donated':donated,'total':MUSEUM_TOTAL,
            'next_milestone':({'at':nxt,'reward':MUSEUM_MILESTONES[nxt],'to_go':nxt-donated} if nxt else None)}

def monster_goals(root):
    kills = Counter()
    for blk in root.iter('specificMonstersKilled'):
        for item in blk.findall('item'):
            nm = item.find('key/string'); c = item.find('value/int')
            if nm is not None and c is not None:
                kills[nm.text] += int(c.text)
    out = []
    for name,target,members,reward in GOALS:
        cur = sum(kills[m] for m in members)
        out.append({'goal':name,'killed':cur,'target':target,
                    'complete':cur>=target,'reward':None if reward=='-' else reward})
    return out

def friendships(root):
    out = {}
    for p in _players(root):
        fd = p.find('friendshipData')
        rel = []
        if fd is not None:
            for item in fd.findall('item'):
                nm = item.find('key/string'); pts = item.find('value/Friendship/Points')
                if nm is not None and pts is not None:
                    rel.append({'villager':nm.text,'hearts':int(pts.text)//250,'points':int(pts.text)})
        rel.sort(key=lambda r:-r['points'])
        out[_t(p,'name')] = {'spouse':_t(p,'spouse') or None,'relationships':rel}
    return out

DATABLE = {'Abigail','Penny','Leah','Maru','Haley','Emily',
           'Alex','Elliott','Harvey','Sam','Sebastian','Shane'}
# in-game Perfection Tracker: (category, save-total, weight%) - verified vs wiki
PERFECTION_SPEC = [
 ('Produce & Forage Shipped', 154, 15), ('Obelisks on Farm', 4, 4),
 ('Golden Clock on Farm', 1, 10), ('Monster Slayer Hero', 12, 10),
 ('Great Friends', 34, 11), ('Farmer Skills at 10', 5, 5),
 ('Stardrops Found', 7, 10), ('Cooking Recipes Made', 81, 10),
 ('Crafting Recipes Made', 149, 10), ('Fish Caught', 72, 10),
 ('Golden Walnuts Found', 130, 5),
]

def perfection(root):
    """Full weighted Perfection % (per the in-game Perfection Tracker), with each
    category's have/total and earned percentage. Verified weights vs wiki."""
    host = root.find('player')
    def n(tag):
        e = host.find(tag); return len(e.findall('item')) if e is not None else 0
    shipped = n('basicShipped'); cooking = n('recipesCooked'); fish = n('fishCaught')
    cr = host.find('craftingRecipes')
    crafting = sum(1 for it in cr.findall('item')
                   if it.find('value/int') is not None and int(it.find('value/int').text) > 0) if cr is not None else 0
    lv = [int(_t(host, s+'Level', 0)) for s in ['farming','fishing','foraging','mining','combat']]
    skills10 = sum(1 for x in lv if x >= 10)
    ms = int(_t(host, 'maxStamina', 270)); stardrops = max(0, min(7, (ms-270)//34))
    gw = next(iter(root.iter('goldenWalnutsFound')), None)
    walnuts = int(gw.text) if gw is not None and gw.text else 0
    blds = Counter(x.find('buildingType').text for x in root.iter('Building')
                   if x.find('buildingType') is not None)
    obelisks = sum(blds.get(k, 0) for k in ['Earth Obelisk','Water Obelisk','Desert Obelisk','Island Obelisk'])
    gold_clock = 1 if blds.get('Gold Clock', 0) else 0
    monsters = sum(1 for g in monster_goals(root) if g['complete'])
    fr = friendships(root).get(_t(host,'name'), {}).get('relationships', [])
    great = sum(1 for r in fr if r['hearts'] >= (8 if r['villager'] in DATABLE else 10))
    haves = {'Produce & Forage Shipped':shipped,'Obelisks on Farm':obelisks,
             'Golden Clock on Farm':gold_clock,'Monster Slayer Hero':monsters,
             'Great Friends':great,'Farmer Skills at 10':skills10,'Stardrops Found':stardrops,
             'Cooking Recipes Made':cooking,'Crafting Recipes Made':crafting,
             'Fish Caught':fish,'Golden Walnuts Found':walnuts}
    total = 0.0; breakdown = []
    for cat, tot, wt in PERFECTION_SPEC:
        have = haves[cat]; frac = min(1.0, have/tot) if tot else 0.0
        earned = frac*wt; total += earned
        breakdown.append({'category':cat,'have':have,'of':tot,'weight_pct':wt,
                          'earned_pct':round(earned,2),'complete':have>=tot,
                          'remaining':max(0,tot-have)})
    return {'perfection_pct':round(total,1),'breakdown':breakdown,
            'note':'Weighted per the in-game Perfection Tracker (verified vs wiki). Cooking/Crafting '
                   '= recipes MADE (not just known). Shipped = distinct basicShipped vs 154 (may '
                   'differ slightly from the Farm & Forage collection set). Great Friends: datable '
                   'max 8 hearts, others 10.'}

def net_worth(root):
    """Gold + sellable value of everything held (backpacks + chests + machine outputs).
    Data-driven from each item's own base sell price."""
    host = root.find('player'); gold = int(_t(host,'money',0))
    val = 0
    def add(el):
        pr = el.find('price'); st = el.find('stack')
        if pr is not None and pr.text and pr.text.lstrip('-').isdigit():
            return int(pr.text) * (int(st.text) if st is not None and st.text else 1)
        return 0
    for p in _players(root):
        if p.find('items') is not None:
            for it in p.find('items').findall('Item'): val += add(it)
    for _, c in _iter_chests(root):
        if c.find('items') is not None:
            for it in c.find('items').findall('Item'): val += add(it)
    for o in root.iter('Object'):
        held = o.find('heldObject')
        if held is not None: val += add(held)
    return {'gold':gold,'inventory_value':val,'net_worth':gold+val,
            'note':'Inventory value = sum of item base sell price x quantity across backpacks, '
                   'chests, and machine outputs (from the item price field). Ignores quality '
                   'multipliers and non-item assets (buildings, machines, land).'}

def fish_available(root, season=None, weather=None, time_hr=None, only_uncaught=False):
    season = (season or _t(root,'currentSeason') or '').lower()
    caught = set()
    host = root.find('player'); fc = host.find('fishCaught') if host is not None else None
    # fishCaught keys are item ids; map to names where known
    if fc is not None:
        for item in fc.findall('item'):
            k = item.find('key')
            kid = None
            if k is not None:
                ks = k.find('string'); ki = k.find('int')
                kid = (ks.text if ks is not None else (ki.text if ki is not None else None))
            if kid and ')' in kid: kid = kid.split(')')[-1]   # strip qualifier like (O)
            if kid in ITEM: caught.add(ITEM[kid])
    res = []
    for name,(seasons,weathers,locs,(sh,eh)) in FISH.items():
        if season and season not in seasons: continue
        if weather and 'any' not in weathers and weather.lower() not in weathers: continue
        if only_uncaught and name in caught: continue
        res.append({'fish':name,'seasons':sorted(seasons),'weather':sorted(weathers),
                    'locations':sorted(locs),'time':f'{sh%24 or sh}:00-{(eh-24) if eh>24 else eh}:00',
                    'already_caught':name in caught})
    return {'season':season,'weather':weather or 'any','fish':res}

def full_report(root):
    return {'overview':overview(root),'players':players(root),
            'community_center':community_center(root),'inventory':inventory(root),
            'processing':processing(root),'feed':feed(root),'museum':museum(root),
            'monster_goals':monster_goals(root),'friendships':friendships(root),
            'perfection':perfection(root),'tools':tools(root),'wallet':wallet(root),
            'can_complete_now':can_complete_now(root),'missing_museum':missing_museum(root),
            'mods':detect_mods(root)}

# ============================ added feature data ===========================
TOOL_TIER = {0:'Base',1:'Copper',2:'Steel',3:'Gold',4:'Iridium'}
TOOL_KINDS = {'Pickaxe','Axe','Hoe','WateringCan','Pan'}

WALLET_FLAGS = {'Rusty Key':'hasRustyKey','Skull Key':'hasSkullKey','Club Card':'hasClubCard',
 'Special Charm':'hasSpecialCharm','Dark Talisman':'hasDarkTalisman','Magic Ink':'hasMagicInk',
 'Town Key':'hasTownKey','Understand Dwarves':'canUnderstandDwarves',
 'Magnifying Glass':'hasMagnifyingGlass','Bear Knowledge':'hasUsedDwarvishTranslationGuide'}

# Full museum donation set (95): 53 minerals + 42 artifacts. IDs are object ids.
MUSEUM_MINERALS = {60:'Emerald',62:'Aquamarine',64:'Ruby',66:'Amethyst',68:'Topaz',70:'Jade',
 72:'Diamond',74:'Prismatic Shard',80:'Quartz',82:'Fire Quartz',84:'Frozen Tear',86:'Earth Crystal',
 538:'Alamite',539:'Bixite',540:'Baryte',541:'Aerinite',542:'Calcite',543:'Dolomite',544:'Esperite',
 545:'Fluorapatite',546:'Geminite',547:'Helvite',548:'Jamborite',549:'Jagoite',550:'Kyanite',
 551:'Lunarite',552:'Malachite',553:'Neptunite',554:'Lemon Stone',555:'Nekoite',556:'Orpiment',
 557:'Petrified Slime',558:'Thunder Egg',559:'Pyrite',560:'Ocean Stone',561:'Ghost Crystal',
 562:'Tigerseye',563:'Jasper',564:'Opal',565:'Fire Opal',566:'Celestine',567:'Marble',
 568:'Sandstone',569:'Granite',570:'Basalt',571:'Limestone',572:'Soapstone',573:'Hematite',
 574:'Mudstone',575:'Obsidian',576:'Slate',577:'Fairy Stone',578:'Star Shards'}
MUSEUM_ARTIFACTS = {96:'Dwarf Scroll I',97:'Dwarf Scroll II',98:'Dwarf Scroll III',99:'Dwarf Scroll IV',
 100:'Chipped Amphora',101:'Arrowhead',103:'Ancient Doll',104:'Elvish Jewelry',105:'Chewing Stick',
 106:'Ornamental Fan',107:'Dinosaur Egg',108:'Rare Disc',109:'Ancient Sword',110:'Rusty Spoon',
 111:'Rusty Spur',112:'Rusty Cog',113:'Chicken Statue',114:'Ancient Seed',115:'Prehistoric Tool',
 116:'Dried Starfish',117:'Anchor',118:'Glass Shards',119:'Bone Flute',120:'Prehistoric Handaxe',
 121:'Dwarvish Helm',122:'Dwarf Gadget',123:'Ancient Drum',124:'Golden Mask',125:'Golden Relic',
 126:'Strange Doll (green)',127:'Strange Doll (yellow)',579:'Prehistoric Scapula',
 580:'Prehistoric Tibia',581:'Prehistoric Skull',582:'Skeletal Hand',583:'Prehistoric Rib',
 584:'Prehistoric Vertebra',585:'Skeletal Tail',586:'Nautilus Fossil',587:'Amphibian Fossil',
 588:'Palm Fossil',589:'Trilobite'}
MUSEUM_SOURCE = {'minerals':'Geodes (cracked at Clint), mining nodes, panning, Omni Geodes.',
 'artifacts':'Artifact spots (hoe the wriggling worms; location-specific), geodes, fishing '
             'treasure chests, digging, and some monster drops.'}

def _donated_ids(root):
    mp = next(iter(root.iter('museumPieces')), None)
    ids = set()
    if mp is not None:
        for item in mp.findall('item'):
            v = item.find('value/string')
            if v is None: v = item.find('value/int')
            if v is not None and v.text is not None:
                t = v.text
                if ')' in t: t = t.split(')')[-1]   # strip qualifier prefix
                if t.lstrip('-').isdigit(): ids.add(int(t))
    return ids

def tools(root):
    out = {}
    for p in _players(root):
        lst = []
        items = p.find('items')
        if items is not None:
            for it in items.findall('Item'):
                kind = it.get(XSI); nm = _t(it,'name')
                if kind in TOOL_KINDS:
                    up = it.find('upgradeLevel')
                    lvl = int(up.text) if up is not None and up.text else None
                    lst.append({'kind':kind,'name':nm,
                                'tier':TOOL_TIER.get(lvl,'?') if lvl is not None else '?',
                                'upgrade_level':lvl})
                elif kind in ('FishingRod','Pan'):
                    lst.append({'kind':kind,'name':nm})
        out[_t(p,'name')] = lst
    return out

def wallet(root):
    host = root.find('player')
    out = {}
    for label, tag in WALLET_FLAGS.items():
        e = host.find(tag)
        out[label] = (e is not None and e.text == 'true')
    return out

def can_complete_now(root):
    """Which incomplete CC bundles you could finish from items currently held.
    Presence-only: ignores required quality/quantity, so treat as 'candidates'."""
    inv = _combined_inventory(root)
    cc = community_center(root)
    res = []
    for b in cc['incomplete_bundles']:
        needed = b['items_remaining']
        have = [i for i in needed if inv.get(i, 0) > 0]
        res.append({'room':b['room'],'bundle':b['bundle'],'need_count':b['need_count'],
                    'you_have':have,'have_count':len(have),
                    'completable_now': len(have) >= b['need_count']})
    return {'note':'Presence-only (ignores required quality/quantity).',
            'ready': [r for r in res if r['completable_now']],
            'partial': [r for r in res if not r['completable_now'] and r['have_count']>0],
            'all': res}

def missing_museum(root):
    donated = _donated_ids(root)
    miss_min = sorted(n for i,n in MUSEUM_MINERALS.items() if i not in donated)
    miss_art = sorted(n for i,n in MUSEUM_ARTIFACTS.items() if i not in donated)
    # self-validation: donated ids that aren't in our table (would signal a table error)
    known = set(MUSEUM_MINERALS)|set(MUSEUM_ARTIFACTS)
    unknown = sorted(donated - known)
    return {'donated':len(donated),'total':95,
            'missing_minerals':miss_min,'missing_artifacts':miss_art,
            'missing_count':len(miss_min)+len(miss_art),
            'sources':MUSEUM_SOURCE,
            'unmapped_donated_ids':unknown}


def detect_mods(root):
    """Detect whether mods are involved and report what the parser could NOT map
    to vanilla references. Data-driven fields (inventory names, category-based
    classification, bundle structure) still reflect the whole save; only the
    unmappable modded pieces are flagged/excluded."""
    meta = _object_meta(root)
    modded_items = sorted(n for n, m in meta.items() if not m.get('vanilla', True))
    cc = community_center(root)
    unmapped_bundle = sorted({it for b in cc['incomplete_bundles']
                              for it in b['items_remaining'] if it.startswith('#')})
    unmapped_museum = missing_museum(root)['unmapped_donated_ids']
    signals = []
    if modded_items:
        signals.append(f"{len(modded_items)} item(s) with non-vanilla ids present")
    if unmapped_bundle:
        signals.append(f"{len(unmapped_bundle)} Community Center bundle item(s) not in the vanilla map")
    if unmapped_museum:
        signals.append(f"{len(unmapped_museum)} museum donation id(s) outside the vanilla 95-item set")
    return {'mods_detected': bool(signals),
            'signals': signals,
            'modded_items': modded_items,
            'unmapped_bundle_items': unmapped_bundle,
            'unmapped_museum_ids': unmapped_museum,
            'note': ("Vanilla-reference outputs (museum set, keg/jar categories) exclude "
                     "modded content and say so. Data-driven outputs (inventory, category "
                     "classification, bundle structure read from the save) include everything. "
                     "For full modded-name resolution, load Data/Objects + the Mods folder "
                     "(not yet implemented).")}

# ======================= player-life helpers ==============================
SEASON_ORDER = ['spring','summer','fall','winter']
FESTIVALS = {
 ('spring',13):'Egg Festival',('spring',24):'Flower Dance',
 ('spring',15):'Desert Festival (15-17)',('spring',16):'Desert Festival',('spring',17):'Desert Festival',
 ('summer',11):'Luau',('summer',20):'Trout Derby (20-21)',('summer',21):'Trout Derby',
 ('summer',28):'Dance of the Moonlight Jellies',
 ('fall',16):'Stardew Valley Fair',('fall',27):"Spirit's Eve",
 ('winter',8):'Festival of Ice',('winter',12):'SquidFest (12-13)',('winter',13):'SquidFest',
 ('winter',15):'Night Market (15-17)',('winter',16):'Night Market',('winter',17):'Night Market',
 ('winter',25):'Feast of the Winter Star',
}
# universal loves (vanilla) + a curated set of each villager's notable loves.
# NOTE: summary for quick use; full/authoritative lists via wiki_page(villager).
UNIVERSAL_LOVES = ['Prismatic Shard','Pearl','Magic Rock Candy','Golden Pumpkin','Rabbit\'s Foot']
LOVED_GIFTS = {
 'Abigail':['Amethyst','Banana Pudding','Blackberry Cobbler','Chocolate Cake','Pumpkin','Spicy Eel'],
 'Alex':['Complete Breakfast','Salmon Dinner'],
 'Caroline':['Fish Taco','Green Tea','Summer Spangle','Tropical Curry'],
 'Clint':['Amethyst','Aquamarine','Artichoke Dip','Emerald','Fiddlehead Risotto','Gold Bar','Iridium Bar','Jade','Omni Geode','Ruby','Topaz'],
 'Demetrius':['Bean Hotpot','Ice Cream','Rice Pudding','Strawberry'],
 'Dwarf':['Amethyst','Aquamarine','Emerald','Lemon Stone','Omni Geode','Ruby','Topaz'],
 'Elliott':['Crab Cakes','Duck Feather','Lobster','Pomegranate','Squid Ink','Tom Kha Soup'],
 'Emily':['Amethyst','Aquamarine','Cloth','Emerald','Jade','Ruby','Survival Burger','Topaz','Wool'],
 'Evelyn':['Beet','Chocolate Cake','Diamond','Fairy Rose','Stuffing','Tulip'],
 'George':['Fried Mushroom','Leek'],
 'Gus':['Diamond','Escargot','Fish Taco','Orange'],
 'Haley':['Coconut','Fruit Salad','Pink Cake','Sunflower'],
 'Harvey':['Coffee','Pickles','Super Meal','Truffle Oil','Wine'],
 'Jas':['Fairy Rose','Pink Cake','Plum Pudding'],
 'Jodi':['Chocolate Cake','Crispy Bass','Diamond','Eggplant Parmesan','Fried Eel','Pancakes','Rhubarb Pie','Vegetable Medley'],
 'Kent':['Fiddlehead Risotto','Roasted Hazelnuts','Daffodil'],
 'Krobus':['Diamond','Iridium Bar','Pumpkin','Void Egg','Void Mayonnaise','Wild Horseradish'],
 'Leah':['Goat Cheese','Poppyseed Muffin','Salad','Stir Fry','Truffle','Wine'],
 'Lewis':['Autumn\'s Bounty','Glazed Yams','Green Tea','Hot Pepper','Vegetable Medley'],
 'Linus':['Blueberry Tart','Cactus Fruit','Coconut','Dish O\' The Sea','Yam'],
 'Marnie':['Diamond','Farmer\'s Lunch','Pink Cake','Pumpkin Pie'],
 'Maru':['Battery Pack','Cauliflower','Cheese Cauliflower','Diamond','Gold Bar','Iridium Bar','Miner\'s Treat','Pepper Poppers','Rhubarb Pie','Strawberry'],
 'Pam':['Beer','Cactus Fruit','Glazed Yams','Mango','Parsnip','Parsnip Soup','Pale Ale'],
 'Penny':['Diamond','Emerald','Melon','Poppy','Poppyseed Muffin','Red Plate','Roots Platter','Sandfish','Tom Kha Soup'],
 'Pierre':['Fried Calamari'],
 'Robin':['Goat Cheese','Peach','Spaghetti'],
 'Sam':['Cactus Fruit','Maple Bar','Pizza','Tigerseye'],
 'Sandy':['Crocus','Daffodil','Mango','Sweet Pea'],
 'Sebastian':['Frozen Tear','Obsidian','Pumpkin Soup','Sashimi','Void Egg'],
 'Shane':['Beer','Hot Pepper','Pepper Poppers','Pizza'],
 'Vincent':['Cranberry Candy','Ginger Ale','Grape','Pink Cake','Snail'],
 'Wizard':['Purple Mushroom','Solar Essence','Super Cucumber','Void Essence'],
 'Willy':['Catfish','Diamond','Iridium Bar','Mango','Octopus','Pumpkin','Sea Cucumber','Sturgeon'],
 'Leo':['Duck Feather','Mango','Ostrich Egg','Parrot Egg','Poi'],
}

def npc_birthdays(root):
    """{name: {'season','day'}} read straight from the save's NPCs (accurate, mod-inclusive)."""
    out = {}
    for n in root.iter('NPC'):
        nm = n.find('name'); bs = n.find('birthday_Season'); bd = n.find('birthday_Day')
        if nm is not None and bs is not None and bs.text and bd is not None and bd.text and bd.text != '0':
            if nm.text not in out:
                out[nm.text] = {'season': bs.text, 'day': int(bd.text)}
    return out

def _days_until(cur_season, cur_day, tgt_season, tgt_day):
    ci = SEASON_ORDER.index(cur_season) if cur_season in SEASON_ORDER else 0
    ti = SEASON_ORDER.index(tgt_season) if tgt_season in SEASON_ORDER else 0
    cur_abs = ci*28 + cur_day
    tgt_abs = ti*28 + tgt_day
    d = tgt_abs - cur_abs
    return d if d >= 0 else d + 112   # wrap to next year

def machines_ready(root):
    """Placed machines whose product is ready to collect (name, product, count)."""
    from collections import Counter
    ready = Counter()
    for o in root.iter('Object'):
        rfh = o.find('readyForHarvest')
        if rfh is not None and rfh.text == 'true':
            held = o.find('heldObject'); mn = o.find('name')
            hn = held.find('name') if held is not None else None
            ready[(mn.text if mn is not None else '?', hn.text if hn is not None else '?')] += 1
    return [{'machine':m,'product':p,'count':c} for (m,p),c in ready.most_common()]

def crops_ready(root):
    """Count of crops fully grown / ready to harvest in tilled soil."""
    ready = 0; growing = 0
    for hd in root.iter('HoeDirt'):
        c = hd.find('crop')
        if c is None: continue
        dead = c.find('dead')
        if dead is not None and dead.text == 'true': continue
        phases = c.find('phaseDays'); cur = c.find('currentPhase')
        fully = c.find('fullyGrown')
        nphases = len(phases.findall('int')) if phases is not None else 0
        curp = int(cur.text) if cur is not None and cur.text else 0
        if (fully is not None and fully.text == 'true') or (nphases and curp >= nphases-1):
            ready += 1
        else:
            growing += 1
    return {'ready': ready, 'still_growing': growing}

def gift_birthday(root, upcoming_days=14):
    """Per-villager birthday (from save) + host hearts + notable loved gifts, and
    which loved gifts you currently hold. Plus birthdays in the next N days."""
    bdays = npc_birthdays(root)
    ov = overview(root); season = ov['date']['season']; day = ov['date']['day']
    hearts = {}
    fr = friendships(root)
    host = ov['host']
    for r in fr.get(host, {}).get('relationships', []):
        hearts[r['villager']] = r['hearts']
    inv = _combined_inventory(root)
    villagers = []
    for name, bd in sorted(bdays.items()):
        loves = LOVED_GIFTS.get(name, [])
        have = [g for g in loves if inv.get(g, 0) > 0]
        du = _days_until(season, day, bd['season'], bd['day'])
        villagers.append({'villager':name,'birthday':f"{bd['season'].title()} {bd['day']}",
                          'days_until_birthday':du,'hearts':hearts.get(name),
                          'loved_gifts':loves,'loved_in_inventory':have})
    upcoming = sorted([v for v in villagers if v['days_until_birthday'] <= upcoming_days],
                      key=lambda v:v['days_until_birthday'])
    return {'today':f"{season.title()} {day}",'universal_loves':UNIVERSAL_LOVES,
            'upcoming_birthdays':upcoming,'villagers':villagers,
            'note':'Birthdays read from the save (accurate). Loved gifts are a curated summary '
                   '(+8x friendship on birthday); use wiki_page(villager) for the full list. '
                   'Give gifts max 2x/week per villager.'}

def daily_briefing(root):
    """One-call morning digest built from the save."""
    ov = overview(root); season = ov['date']['season']; day = ov['date']['day']
    dl = next(iter(root.iter('dailyLuck')), None)
    luck = float(dl.text) if dl is not None and dl.text else 0.0
    luck_txt = ('very lucky' if luck>0.07 else 'lucky' if luck>0 else 'neutral' if luck==0
                else 'unlucky' if luck>-0.07 else 'very unlucky')
    bd = gift_birthday(root, upcoming_days=7)
    today_bd = [v['villager'] for v in bd['villagers'] if v['days_until_birthday']==0]
    fests = []
    for d in range(0, 8):
        s_idx = (SEASON_ORDER.index(season)*28 + day + d)
        s = SEASON_ORDER[(s_idx-1)//28 % 4]; dd = (s_idx-1)%28 + 1
        if (s,dd) in FESTIVALS:
            fests.append({'in_days':d,'date':f"{s.title()} {dd}",'festival':FESTIVALS[(s,dd)]})
    mr = machines_ready(root); cr = crops_ready(root)
    animals = list(root.iter('FarmAnimal'))
    unpet = sum(1 for a in animals if a.find('wasPet') is not None and a.find('wasPet').text=='false')
    return {'date':f"{season.title()} {day}, Year {ov['date']['year']}",
            'daily_luck':{'value':luck,'assessment':luck_txt},
            'birthdays_today':today_bd,
            'upcoming_birthdays':[{'villager':v['villager'],'in_days':v['days_until_birthday'],
                                   'have_loved_gift':bool(v['loved_in_inventory'])}
                                  for v in bd['upcoming_birthdays']],
            'festivals_next_7_days':fests,
            'machines_ready':{'total':sum(m['count'] for m in mr),'breakdown':mr},
            'crops_ready_to_harvest':cr['ready'],
            'animals_to_pet':unpet,'total_animals':len(animals),
            'note':'Everything read from the save. Pet animals + collect machines daily; '
                   'gift birthday villagers a loved item for +8x friendship.'}

# ======================= container location tools =========================
# playerChoiceColor RGB -> the in-game chest color name (the 20-color wheel).
CHEST_COLORS = {
 (0,0,0):'default', (167,20,20):'red', (255,105,18):'orange', (255,204,0):'yellow',
 (159,236,0):'green', (0,220,150):'teal', (0,190,255):'cyan', (0,100,255):'blue',
 (120,0,255):'purple', (255,0,255):'magenta', (255,120,200):'pink', (110,55,20):'brown',
 (150,150,150):'gray', (255,255,255):'white',
}
def _color_name(rgb):
    if rgb is None: return None
    if rgb == (0,0,0): return 'default'
    if rgb in CHEST_COLORS: return CHEST_COLORS[rgb]
    # nearest of the known palette
    best = min(CHEST_COLORS, key=lambda c: sum((a-b)**2 for a,b in zip(c, rgb)))
    return f"~{CHEST_COLORS[best]}"

def _chest_identity(c):
    g = lambda t: (c.find(t).text if c.find(t) is not None else None)
    tl = c.find('tileLocation')
    tile = [int(tl.find('X').text), int(tl.find('Y').text)] if tl is not None else None
    col = c.find('playerChoiceColor')
    rgb = None
    if col is not None and col.find('R') is not None:
        rgb = (int(col.find('R').text), int(col.find('G').text), int(col.find('B').text))
    ct = g('chestType')
    return {'type': g('name') or 'Chest', 'chest_type': ct or 'player',
            'tile': tile, 'color': _color_name(rgb)}

def _iter_chests(root):
    """Yield (location_name, chest_element) for every Chest, tagged with its map."""
    XSI = '{http://www.w3.org/2001/XMLSchema-instance}type'
    for loc in root.iter('GameLocation'):
        ln = loc.find('name'); lname = ln.text if ln is not None and ln.text else '?'
        for c in loc.iter('Object'):
            if c.get(XSI) == 'Chest':
                yield lname, c

def chests(root):
    """Every container: type, location (map + tile), color, item count, and contents."""
    out = []
    for lname, c in _iter_chests(root):
        idc = _chest_identity(c)
        contents = dict(_items_in(c).most_common())
        out.append({'location': lname, **idc,
                    'item_types': len(contents), 'total_items': sum(contents.values()),
                    'contents': contents})
    return {'chest_count': len(out), 'chests': out,
            'note': "color 'default' = uncolored; '~name' = nearest palette color. "
                    "tile is (X,Y) on the named map."}

def find_item(root, name, fuzzy=True):
    """Locate an item across chests, machine outputs, and player backpacks.
    Returns each place holding it with quantity + container location."""
    q = name.strip().lower()
    def match(n):
        n2 = (n or '').lower()
        return n2 == q or (fuzzy and q in n2)
    hits = []; total = 0
    for p in _players(root):
        for it in (p.find('items').findall('Item') if p.find('items') is not None else []):
            nm = it.find('name')
            if nm is not None and nm.text and match(nm.text):
                st = it.find('stack'); qty = int(st.text) if st is not None and st.text else 1
                hits.append({'where':'backpack','holder':_t(p,'name'),'item':nm.text,'qty':qty}); total += qty
    for lname, c in _iter_chests(root):
        idc = _chest_identity(c)
        for it in (c.find('items').findall('Item') if c.find('items') is not None else []):
            nm = it.find('name')
            if nm is not None and nm.text and match(nm.text):
                st = it.find('stack'); qty = int(st.text) if st is not None and st.text else 1
                hits.append({'where':'chest','location':lname,'container':idc['type'],
                             'color':idc['color'],'tile':idc['tile'],'item':nm.text,'qty':qty}); total += qty
    for loc in root.iter('GameLocation'):
        ln = loc.find('name'); lname = ln.text if ln is not None and ln.text else '?'
        for o in loc.iter('Object'):
            held = o.find('heldObject')
            if held is not None:
                hn = held.find('name'); rfh = o.find('readyForHarvest')
                if hn is not None and hn.text and match(hn.text):
                    tl = o.find('tileLocation')
                    tile = [int(tl.find('X').text), int(tl.find('Y').text)] if tl is not None else None
                    mn = o.find('name')
                    hits.append({'where':'machine','location':lname,'machine':mn.text if mn is not None else '?',
                                 'ready': rfh is not None and rfh.text=='true','tile':tile,
                                 'item':hn.text,'qty':1}); total += 1
    return {'query':name,'total_found':total,'places':len(hits),'results':hits,
            'note':'Searches player backpacks, chests, and machine outputs. fuzzy=substring match. '
                   'tile is (X,Y) on the named map.'}
