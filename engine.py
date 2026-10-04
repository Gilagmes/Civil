"""Ядро игры «Цивилизация» v2. Не зависит от Telegram.
Состояние игры — обычный dict (хранится в базе как JSON)."""
import random

VER = 2                # версия формата сохранений
GAME_VERSION = "3.6"   # версия игры (README/CHANGELOG)
W, H = 14, 10          # размер карты
MAX_PLAYERS = 6
MAX_TURNS = 60         # после этого хода побеждает лидер по очкам
UNIT_HP = 10
START_GOLD = 10

TERRAIN = {
    "plains": {"emoji": "🌾", "f": 2, "p": 1, "def": 1.0, "cost": 1, "name": "Равнина"},
    "forest": {"emoji": "🌲", "f": 1, "p": 2, "def": 1.25, "cost": 2, "name": "Лес"},
    "hills": {"emoji": "🗻", "f": 0, "p": 2, "def": 1.25, "cost": 2, "name": "Холмы"},
    "water": {"emoji": "🌊", "f": 2, "p": 0, "def": 1.0, "cost": 99, "name": "Вода"},
}
IMPR = {
    "farm": {"name": "Ферма", "emoji": "🌽", "req": "agriculture", "on": "plains", "f": 1, "p": 0},
    "mine": {"name": "Шахта", "emoji": "🪨", "req": "mining", "on": "hills", "f": 0, "p": 2},
}
JOB_TURNS = 3
TRADE_TURNS = 12       # длительность торгового пути (ходов)
SQUARES = ["🟥", "🟦", "🟩", "🟨", "🟪", "🟧"]   # города игроков
CIRCLES = ["🔴", "🔵", "🟢", "🟡", "🟣", "🟠"]   # юниты игроков

TECHS = {
    "agriculture": {"name": "Земледелие", "cost": 15, "req": []},
    "mining": {"name": "Горное дело", "cost": 15, "req": []},
    "archery": {"name": "Стрельба из лука", "cost": 18, "req": []},
    "pottery": {"name": "Гончарное дело", "cost": 22, "req": ["agriculture"]},
    "bronze": {"name": "Бронзовое дело", "cost": 25, "req": ["mining"]},
    "riding": {"name": "Верховая езда", "cost": 28, "req": ["agriculture"]},
    "writing": {"name": "Письменность", "cost": 30, "req": ["pottery"]},
    "currency": {"name": "Денежное обращение", "cost": 35, "req": ["bronze"]},
    "iron": {"name": "Обработка железа", "cost": 45, "req": ["bronze"]},
    "math": {"name": "Математика", "cost": 45, "req": ["writing", "bronze"]},
    "wheel": {"name": "Колесо", "cost": 28, "req": ["agriculture"], "note": "дороги (движение ×3)"},
    "sailing": {"name": "Мореплавание", "cost": 30, "req": ["pottery"]},
    "philosophy": {"name": "Философия", "cost": 60, "req": ["writing"],
                   "note": "+1🔬 в каждом городе"},
}


def _tech_depth(k):
    return 0 if not TECHS[k]["req"] else 1 + max(_tech_depth(r) for r in TECHS[k]["req"])


for _k, _t in TECHS.items():   # поздние технологии дороже (баланс)
    _t["cost"] = int(_t["cost"] * 1.9 * (1 + 0.2 * _tech_depth(_k)))

DIFFICULTY = {   # множитель производства/науки/золота ИИ и характер ИИ
    "easy": {"name": "Лёгкий", "mult": 0.75},
    "normal": {"name": "Обычный", "mult": 1.0},
    "hard": {"name": "Трудный", "mult": 1.3},
}
CITY_LEVELS = [(1, "🏘 Деревня"), (3, "🏙 Город"), (6, "🌆 Мегаполис")]

UNITS = {
    "settler": {"name": "Поселенец", "cost": 20, "att": 0, "def": 0, "moves": 1, "vision": 1, "req": None},
    "worker": {"name": "Рабочий", "cost": 12, "att": 0, "def": 0, "moves": 1, "vision": 1, "req": None},
    "scout": {"name": "Разведчик", "cost": 10, "att": 0, "def": 1, "moves": 3, "vision": 3, "req": None},
    "warrior": {"name": "Воин", "cost": 10, "att": 3, "def": 3, "moves": 1, "vision": 2, "req": None},
    "archer": {"name": "Лучник", "cost": 14, "att": 4, "def": 4, "moves": 1, "vision": 2, "req": "archery",
               "range": 2},
    "horseman": {"name": "Всадник", "cost": 18, "att": 5, "def": 3, "moves": 2, "vision": 2, "req": "riding"},
    "knight": {"name": "Рыцарь", "cost": 26, "att": 7, "def": 4, "moves": 2, "vision": 2, "req": "riding"},
    "swordsman": {"name": "Мечник", "cost": 20, "att": 6, "def": 5, "moves": 1, "vision": 2, "req": "iron"},
    "crossbowman": {"name": "Арбалетчик", "cost": 20, "att": 6, "def": 4, "moves": 1, "vision": 2,
                    "req": "math", "range": 2},
    "catapult": {"name": "Катапульта", "cost": 24, "att": 8, "def": 2, "moves": 1, "vision": 2, "req": "math",
                 "range": 2},
    "missionary": {"name": "Миссионер", "cost": 20, "att": 0, "def": 0, "moves": 2, "vision": 2, "req": "pottery"},
    "galley": {"name": "Галера", "cost": 22, "att": 3, "def": 3, "moves": 3, "vision": 3, "req": "sailing",
               "naval": True, "cap": 2},
    "trader": {"name": "Караван", "cost": 20, "att": 0, "def": 1, "moves": 2, "vision": 2, "req": "currency"},
}
RESOURCES = {"horses": {"emoji": "🐎", "name": "Лошади", "on": ["plains"]},
             "iron": {"emoji": "🔩", "name": "Железо", "on": ["hills"]},
             "gems": {"emoji": "💎", "name": "Самоцветы", "on": ["hills", "forest"]}}
RES_COUNTS = {"horses": 5, "iron": 5, "gems": 4}
NWONDERS = {   # чудеса природы (одно на клетку, бонус — клетке и/или городу в границах)
    "everest": {"name": "Эверест", "emoji": "🏔", "faith": 2,
                "desc": "+2 веры в ход городам, чьи границы его содержат"},
    "victoria": {"name": "Озеро Виктория", "emoji": "💦", "f": 2, "desc": "+2🌾 к клетке"},
    "kilimanjaro": {"name": "Килиманджаро", "emoji": "⛰️", "p": 2, "desc": "+2⚙️ к клетке"},
    "eldorado": {"name": "Эльдорадо", "emoji": "✨", "gold": 4,
                 "desc": "+4💰 в ход городам, чьи границы его содержат"},
}
UNIT_RES = {"horseman": "horses", "swordsman": "iron", "catapult": "iron",
            "knight": "horses"}   # юнит требует ресурс
UPGRADES = {"warrior": "swordsman", "archer": "crossbowman", "horseman": "knight"}
GEM_GOLD = 3           # золото в ход за каждые самоцветы в вашей земле
ROAD_TURNS, ROAD_COST = 2, 0.34
BELIEFS = {"fertility": ("🌾", "Плодородие", "+2🌾 в городах верующих"),
           "wisdom": ("🔬", "Знание", "+2🔬 в городах верующих"),
           "wealth": ("💰", "Богатство", "+2💰 в городах верующих"),
           "fervor": ("🎭", "Рвение", "+2🎭 культуры в городах верующих")}
RELIGION_NAMES = ["Культ Солнца", "Путь Звезды", "Вера Древа", "Братство Океана"]
FAITH_NEED, SPREAD_RANGE = 30, 4

CIVICS = {   # гражданские институты: изучаются за культуру 🎭 (как в Civ 6)
    "code":    {"name": "Устройство государства", "cost": 20, "req": [], "note": "+1💰 в столице"},
    "craft":   {"name": "Ремесло", "cost": 40, "req": ["code"], "note": "улучшения строятся на ход быстрее"},
    "milt":    {"name": "Военная традиция", "cost": 40, "req": ["code"], "note": "×2 опыт юнитов в бою"},
    "games":   {"name": "Игры и зрелища", "cost": 60, "req": ["craft"], "note": "+2🎭 и +1🏠 в каждом городе"},
    "polphil": {"name": "Политическая философия", "cost": 60, "req": ["milt", "games"], "note": "открывает смену строя"},
    "diplom":  {"name": "Дипломатия", "cost": 80, "req": ["polphil"], "note": "+2💰 в ход с союзных городов-государств"},
}
GOVS = {   # строй государства: выбирается после «Политической философии», менять можно свободно
    "autocracy": ("👑", "Автократия", "+1⚙️ в каждом городе"),
    "monarchy": ("🏰", "Монархия", "защита в городах ×1.25, +1💰 в каждом городе"),
    "republic": ("🏛", "Республика", "+2🔬 и +1🎭 в каждом городе"),
}

BUILDINGS = {
    "granary": {"name": "Амбар (+2🌾)", "cost": 20, "req": "pottery"},
    "library": {"name": "Библиотека (+3🔬)", "cost": 30, "req": "writing"},
    "walls": {"name": "Стены (защита ×1.5)", "cost": 25, "req": "bronze"},
    "market": {"name": "Рынок (+3💰)", "cost": 30, "req": "currency"},
    "workshop": {"name": "Мастерская (+2⚙️)", "cost": 30, "req": "iron"},
    "temple": {"name": "Храм (+2🎭, +2 веры)", "cost": 25, "req": "writing"},
}
WONDERS = {   # можно построить только один раз во всём мире
    "pyramids": {"name": "Пирамиды (+3⚙️)", "cost": 70, "req": "mining"},
    "gardens": {"name": "Висячие сады (+3🌾)", "cost": 60, "req": "pottery"},
    "library": {"name": "Великая библиотека (+4🔬)", "cost": 70, "req": "writing"},
    "colossus": {"name": "Колосс (+5💰)", "cost": 80, "req": "currency"},
}
WONDER_SCORE = 15
BARB = "⚫"            # варвары
BARB_BOUNTY = 10       # награда за убитого варвара
BARB_CAMP_GOLD = 20    # золото за разорение лагеря варваров
HUT_COUNT = 6          # селения (руины) на карте
BORDER_LEVELS = [(0, 1), (12, 2), (35, 3)]   # (культура города, радиус границ)
CS_KINDS = {"trade": "торговое (+3💰/ход союзнику)", "science": "научное (+3🔬/ход союзнику)",
            "military": "военное (воин союзнику раз в 8 ходов)"}
CS_NAMES = ["Женева", "Венеция", "Лхаса", "Брюгге", "Ханьчжоу", "Зимбабве", "Каир"]
CS_ALLY_MIN = 40       # влияние для союза
CS_GIFT = 20           # цена подарка (золото)
CS_GIFT_INF = 12       # влияние за подарок
CS_PEACE_COST = 30     # цена мира с городом-государством
CITY_NAMES = ["Ур", "Вавилон", "Мемфис", "Афины", "Спарта", "Рим", "Карфаген",
              "Персеполь", "Фивы", "Троя", "Киев", "Новгород", "Дели", "Ханой",
              "Куско", "Тикаль", "Милан", "Лион", "Эфес", "Сидон"]
DIRS = {"N": (0, -1), "S": (0, 1), "W": (-1, 0), "E": (1, 0)}
WIN_REASON = {"domination": "господство", "science": "научная победа", "score": "победа по очкам",
              "religion": "религиозная победа"}
REL_WIN_SHARE, REL_WIN_TURNS, REL_WIN_MIN_CITIES = 0.7, 4, 6   # доля городов, ходов подряд, минимум городов в мире


class GameError(Exception):
    """Ошибка игрока (неверный ход). Текст можно показывать пользователю."""


# ---------- вспомогательное ----------

def dist(a, b):
    return max(abs(a[0] - b[0]), abs(a[1] - b[1]))


def _new_id(s):
    i = s["next_id"]
    s["next_id"] += 1
    return str(i)


def _news(s, k, text):
    p = s["players"].get(k)
    if p:
        p["news"].append(text)
        del p["news"][:-12]


def units_at(s, x, y):
    return [(i, u) for i, u in s["units"].items() if u["x"] == x and u["y"] == y]


def city_at(s, x, y):
    for i, c in s["cities"].items():
        if c["x"] == x and c["y"] == y:
            return i, c
    return None


def cs_at(s, x, y):
    for i, c in s.get("cstates", {}).items():
        if c["x"] == x and c["y"] == y:
            return i, c
    return None


def border_radius(c):
    r = 1
    for th, rad in BORDER_LEVELS:
        if c.get("culture", 0) >= th:
            r = rad
    return r


def tile_owners(s):
    """{(x, y): id города} — кому принадлежит клетка по границам городов."""
    res = {}
    for cid, c in s["cities"].items():
        r = border_radius(c)
        for y in range(max(0, c["y"] - r), min(H, c["y"] + r + 1)):
            for x in range(max(0, c["x"] - r), min(W, c["x"] + r + 1)):
                cur = res.get((x, y))
                if cur is None:
                    res[(x, y)] = cid
                else:
                    o = s["cities"][cur]
                    if (dist((x, y), (c["x"], c["y"])), -c.get("culture", 0)) < \
                            (dist((x, y), (o["x"], o["y"])), -o.get("culture", 0)):
                        res[(x, y)] = cid
    return res


def tile_owner(s, x, y, owners=None):
    """Игрок-владелец клетки или None."""
    cid = (owners if owners is not None else tile_owners(s)).get((x, y))
    return s["cities"][cid]["owner"] if cid else None


def spawn(s, owner, typ, x, y):
    i = _new_id(s)
    s["units"][i] = {"owner": owner, "type": typ, "x": x, "y": y, "hp": UNIT_HP,
                     "mv": UNITS[typ]["moves"], "fort": False, "job": None, "left": 0, "xp": 0}
    return i


def promo_level(u):
    """Уровень повышений юнита: 0–3, по 6 опыта за уровень."""
    return min(3, u.get("xp", 0) // 6)


def promo_mult(u):
    return 1 + 0.15 * promo_level(u)


def has_access(s, k, x, y, owners=None):
    """Есть ли у игрока k доступ к клетке: своя земля или ничья в радиусе 2 от его города."""
    o = tile_owner(s, x, y, owners)
    if o == k:
        return True
    return o is None and any(c["owner"] == k and dist((x, y), (c["x"], c["y"])) <= 2
                             for c in s["cities"].values())


def resources_of(s, k):
    owners = tile_owners(s)
    out = {r: 0 for r in RESOURCES}
    for key, r in s.get("res", {}).items():
        x, y = map(int, key.split(","))
        if has_access(s, k, x, y, owners):
            out[r] += 1
    return out


def has_road(s, x, y):
    return f"{x},{y}" in s.get("roads", []) or bool(city_at(s, x, y))


def job_info(job):
    if job == "road":
        return "Дорога", "🛤"
    return IMPR[job]["name"], IMPR[job]["emoji"]


def coastal(s, c):
    return any(0 <= c["x"] + dx < W and 0 <= c["y"] + dy < H and s["map"][c["y"] + dy][c["x"] + dx] == "water"
               for dx in (-1, 0, 1) for dy in (-1, 0, 1))


def _cargo(s, boat_id):
    return sum(1 for v in s["units"].values() if v.get("aboard") == boat_id)


def _kill_unit(s, uid):
    """Удаляет юнит (и пассажиров, если это корабль)."""
    s["units"].pop(uid, None)
    for i in [i for i, v in s["units"].items() if v.get("aboard") == uid]:
        del s["units"][i]


def _spawn_at(s, owner, key, c):
    x, y = c["x"], c["y"]
    if UNITS[key].get("naval"):
        for dx, dy in list(DIRS.values()) + [(1, 1), (1, -1), (-1, 1), (-1, -1)]:
            nx, ny = x + dx, y + dy
            if 0 <= nx < W and 0 <= ny < H and s["map"][ny][nx] == "water":
                x, y = nx, ny
                break
    return spawn(s, owner, key, x, y)


def own_unit(s, owner, uid):
    u = s["units"].get(uid)
    if not u or u["owner"] != owner:
        raise GameError("Юнит не найден")
    return u


def own_city(s, owner, cid):
    c = s["cities"].get(cid)
    if not c or c["owner"] != owner:
        raise GameError("Город не найден")
    return c


def item_data(item):
    kind, key = item.split(":")
    return {"unit": UNITS, "bld": BUILDINGS, "wnd": WONDERS}[kind][key]


def tile_yield(s, x, y):
    t = TERRAIN[s["map"][y][x]]
    f, p = t["f"], t["p"]
    im = s["impr"].get(f"{x},{y}")
    if im:
        f += IMPR[im]["f"]
        p += IMPR[im]["p"]
    wn = s.get("nwonders", {}).get(f"{x},{y}")
    if wn:
        f += NWONDERS[wn].get("f", 0)
        p += NWONDERS[wn].get("p", 0)
    return f, p


# ---------- туман войны ----------

def visible(s, k):
    vis = set()

    def add(x0, y0, r):
        for y in range(max(0, y0 - r), min(H, y0 + r + 1)):
            for x in range(max(0, x0 - r), min(W, x0 + r + 1)):
                vis.add((x, y))
    for u in s["units"].values():
        if u["owner"] == k:
            add(u["x"], u["y"], UNITS[u["type"]]["vision"])
    for c in s["cities"].values():
        if c["owner"] == k:
            add(c["x"], c["y"], 2)
    return vis


def refresh(s, k):
    seen = s["players"][k]["seen"]
    for x, y in visible(s, k):
        seen[y * W + x] = 1


# ---------- создание игры ----------

def new_game(owner, seed=None):
    rng = random.Random(seed)
    rows = []
    for y in range(H):
        row = []
        for x in range(W):
            border = x in (0, W - 1) or y in (0, H - 1)
            if rng.random() < (0.5 if border else 0.12):
                row.append("water")
            else:
                row.append(rng.choices(["plains", "forest", "hills"], [5, 3, 2])[0])
        rows.append(row)
    land = [f"{x},{y}" for y in range(H) for x in range(W) if rows[y][x] != "water"]
    huts = rng.sample(land, min(HUT_COUNT, len(land)))
    res = {}
    for name, n in RES_COUNTS.items():
        cands = [k for k in land if rows[int(k.split(",")[1])][int(k.split(",")[0])] in RESOURCES[name]["on"]
                 and k not in res]
        for k in rng.sample(cands, min(n, len(cands))):
            res[k] = name
    nwonders = {}
    free = [k for k in land if k not in res and k not in huts]
    for key in rng.sample(sorted(NWONDERS), min(3, len(free))):
        pos = rng.choice(free)
        free.remove(pos)
        nwonders[pos] = key
    return {"ver": VER, "huts": huts, "res": res, "roads": [], "owner": str(owner), "turn": 0, "started": False,
            "winner": None, "win_reason": None, "deadline": None, "map": rows,
            "impr": {}, "rel": {}, "offers": [], "wonders": {}, "camps": [], "nwonders": nwonders,
            "players": {}, "cities": {}, "units": {}, "next_id": 1}


def add_player(s, uid, name):
    if s["started"]:
        raise GameError("Игра уже началась")
    k = str(uid)
    if k in s["players"]:
        raise GameError("Вы уже в игре")
    if len(s["players"]) >= MAX_PLAYERS:
        raise GameError("Свободных мест нет")
    s["players"][k] = {"name": name, "color": len(s["players"]), "alive": True,
                       "ready": False, "techs": [], "research": None, "progress": 0,
                       "gold": START_GOLD, "seen": [0] * (W * H), "news": [],
                       "civics": [], "civic": None, "cprogress": 0, "gov": None}


def difficulty(s):
    return s.get("difficulty", "normal")


def set_difficulty(s, level):
    if s["started"]:
        raise GameError("Сложность можно менять только до начала игры")
    if level not in DIFFICULTY:
        raise GameError("Сложность: easy, normal или hard")
    s["difficulty"] = level


def ai_mult(s, k):
    return DIFFICULTY[difficulty(s)]["mult"] if s["players"][k].get("ai") else 1.0


def add_ai(s, name):
    """Добавляет игрока-компьютер (ходит через ai.play_all)."""
    if s["started"]:
        raise GameError("Игра уже началась")
    if len(s["players"]) >= MAX_PLAYERS:
        raise GameError("Свободных мест нет")
    n = 1
    while f"ai{n}" in s["players"]:
        n += 1
    add_player(s, f"ai{n}", name)
    s["players"][f"ai{n}"]["ai"] = True


def start(s, seed=None):
    if s["started"]:
        raise GameError("Игра уже идёт")
    rng = random.Random(seed)
    land = [(x, y) for y in range(H) for x in range(W) if s["map"][y][x] != "water"]
    rng.shuffle(land)
    n = len(s["players"])
    starts = []
    for need in (6, 5, 4, 3, 2, 1, 0):
        starts = []
        for p in land:
            if all(dist(p, q) >= need for q in starts):
                starts.append(p)
            if len(starts) == n:
                break
        if len(starts) == n:
            break
    for k, (x, y) in zip(s["players"], starts):
        spawn(s, k, "settler", x, y)
        spawn(s, k, "warrior", x, y)
        spawn(s, k, "worker", x, y)
        refresh(s, k)
    s["huts"] = [h for h in s.get("huts", [])
                 if all(dist(tuple(map(int, h.split(","))), st) > 2 for st in starts)]
    kinds = ["trade", "science", "military"]
    rng.shuffle(kinds)
    names = CS_NAMES[:]
    rng.shuffle(names)
    s["cstates"] = {}
    placed = []
    for kind in kinds[:2 if n <= 3 else 3]:
        for pos in land:
            if all(dist(pos, st) >= 3 for st in starts) and all(dist(pos, q) >= 4 for q in placed):
                placed.append(pos)
                s["cstates"][_new_id(s)] = {"name": names.pop(), "x": pos[0], "y": pos[1], "kind": kind,
                                            "inf": {}, "war": [], "ally": None}
                break
    s["huts"] = [h for h in s["huts"] if tuple(map(int, h.split(","))) not in placed]
    target = max(2, min(4, n + 1))
    huts_pos = [tuple(map(int, h.split(","))) for h in s["huts"]]
    s["camps"] = []
    for need_s, need_c in ((5, 4), (4, 3), (3, 2), (2, 1)):   # лагеря варваров — подальше от стартов
        camps = []
        for pos in land:
            if (all(dist(pos, st) >= need_s for st in starts)
                    and all(dist(pos, q) >= need_c for q in placed)
                    and all(dist(pos, h) >= 2 for h in huts_pos)
                    and all(dist(pos, tuple(map(int, c.split(",")))) >= 3 for c in camps)):
                camps.append(f"{pos[0]},{pos[1]}")
                if len(camps) >= target:
                    break
        if len(camps) >= min(2, target):
            s["camps"] = camps
            break
    s["started"] = True
    s["turn"] = 1


# ---------- дипломатия ----------

def _rk(a, b):
    return "|".join(sorted([a, b]))


def relation(s, a, b):
    if "barb" in (a, b):
        return "war"
    return s["rel"].get(_rk(a, b), "peace")


def _check_other(s, a, b):
    if b == a or b not in s["players"] or not s["players"][b]["alive"]:
        raise GameError("Такого игрока нет")


def declare_war(s, a, b):
    _check_other(s, a, b)
    if relation(s, a, b) == "war":
        raise GameError("Вы уже воюете")
    s["rel"][_rk(a, b)] = "war"
    s["offers"] = [o for o in s["offers"] if set(o) != {a, b}]
    na, nb = s["players"][a]["name"], s["players"][b]["name"]
    _news(s, b, f"⚔️ {na} объявил вам войну!")
    return "Война объявлена", f"⚔️ {na} объявил войну игроку {nb}!"


def propose_peace(s, a, b):
    _check_other(s, a, b)
    if relation(s, a, b) != "war":
        raise GameError("Вы и так в мире")
    if [b, a] in s["offers"]:
        return accept_peace(s, a, b)
    if [a, b] not in s["offers"]:
        s["offers"].append([a, b])
        _news(s, b, f"🕊 {s['players'][a]['name']} предлагает мир (меню «Дипломатия»)")
    return "Предложение мира отправлено", None


def accept_peace(s, a, b):
    _check_other(s, a, b)
    if [b, a] not in s["offers"]:
        raise GameError("Нет предложения мира")
    s["rel"][_rk(a, b)] = "peace"
    s["offers"] = [o for o in s["offers"] if set(o) != {a, b}]
    na, nb = s["players"][a]["name"], s["players"][b]["name"]
    return "Мир заключён", f"🕊 {na} и {nb} заключили мир"


# ---------- технологии ----------

def available_techs(s, owner):
    known = s["players"][owner]["techs"]
    return [k for k, t in TECHS.items() if k not in known and all(r in known for r in t["req"])]


def unlocks(tech):
    names = [v["name"].split(" (")[0] for v in UNITS.values() if v["req"] == tech]
    names += [v["name"].split(" (")[0] for v in BUILDINGS.values() if v["req"] == tech]
    names += ["чудо: " + v["name"].split(" (")[0] for v in WONDERS.values() if v["req"] == tech]
    names += [v["name"] for v in IMPR.values() if v["req"] == tech]
    if TECHS[tech].get("note"):
        names.append(TECHS[tech]["note"])
    return ", ".join(names) or "—"


def set_research(s, owner, tech):
    p = s["players"][owner]
    if tech not in available_techs(s, owner):
        raise GameError("Эту технологию пока изучить нельзя")
    if p["research"] != tech:
        p["research"] = tech
        p["progress"] = 0
    return "Исследование выбрано"


# ---------- действия игрока ----------

def cs_ally(cs):
    inf = cs["inf"]
    if not inf:
        return None
    k = max(inf, key=lambda q: inf[q])
    top = inf[k]
    if top < CS_ALLY_MIN or sum(1 for v in inf.values() if v == top) > 1:
        return None
    return k


def _cs_get(s, csid):
    cs = s.get("cstates", {}).get(csid)
    if not cs:
        raise GameError("Этого города-государства больше нет")
    return cs


def cs_gift(s, owner, csid):
    cs = _cs_get(s, csid)
    if owner in cs["war"]:
        raise GameError("Вы воюете с этим городом-государством. Сначала заключите мир")
    p = s["players"][owner]
    if p["gold"] < CS_GIFT:
        raise GameError(f"Нужно {CS_GIFT}💰, у вас {p['gold']}")
    p["gold"] -= CS_GIFT
    cs["inf"][owner] = min(100, cs["inf"].get(owner, 0) + CS_GIFT_INF)
    return f"Подарок принят. Влияние: {cs['inf'][owner]} (союз с {CS_ALLY_MIN})"


def cs_declare_war(s, owner, csid):
    cs = _cs_get(s, csid)
    if owner in cs["war"]:
        raise GameError("Вы уже воюете")
    cs["war"].append(owner)
    cs["inf"][owner] = 0
    return "Война объявлена", f"⚔️ {s['players'][owner]['name']} объявил войну городу-государству «{cs['name']}»!"


def cs_make_peace(s, owner, csid):
    cs = _cs_get(s, csid)
    if owner not in cs["war"]:
        raise GameError("Вы не воюете")
    p = s["players"][owner]
    if p["gold"] < CS_PEACE_COST:
        raise GameError(f"Мир стоит {CS_PEACE_COST}💰, у вас {p['gold']}")
    p["gold"] -= CS_PEACE_COST
    cs["war"].remove(owner)
    return "Мир заключён"


def found_city(s, owner, uid):
    u = own_unit(s, owner, uid)
    if u["type"] != "settler":
        raise GameError("Города основывают только поселенцы")
    if s["map"][u["y"]][u["x"]] == "water":
        raise GameError("Нельзя строить на воде")
    if any(dist((q["x"], q["y"]), (u["x"], u["y"])) < 3 for q in s.get("cstates", {}).values()):
        raise GameError("Слишком близко к городу-государству (нужно ≥ 3 клеток)")
    to = tile_owner(s, u["x"], u["y"])
    if to and to != owner:
        raise GameError("Это чужая территория")
    for c in s["cities"].values():
        if dist((c["x"], c["y"]), (u["x"], u["y"])) < 3:
            raise GameError("Слишком близко к другому городу (нужно ≥ 3 клеток)")
    if f"{u['x']},{u['y']}" in s.get("camps", []):
        s["camps"].remove(f"{u['x']},{u['y']}")
    cid = _new_id(s)
    name = CITY_NAMES[len(s["cities"]) % len(CITY_NAMES)]
    capital = not any(c["owner"] == owner for c in s["cities"].values())
    s["cities"][cid] = {"owner": owner, "name": name, "x": u["x"], "y": u["y"],
                        "pop": 1, "food": 0, "prod": 0, "build": None,
                        "buildings": [], "wonders": [], "capital": capital, "culture": 0}
    del s["units"][uid]
    refresh(s, owner)
    return f"Основан город {name}!" + (" Это ваша столица." if capital else "")


def join_city(s, owner, uid):
    """Поселенец вливается в свой город (+1 население). Возвращает сообщение."""
    u = own_unit(s, owner, uid)
    if u["type"] != "settler":
        raise GameError("Вливаться в город могут только поселенцы")
    c = next((c for c in s["cities"].values()
              if c["owner"] == owner and (c["x"], c["y"]) == (u["x"], u["y"])), None)
    if not c:
        raise GameError("Встаньте в свой город")
    if c["pop"] >= housing(s, c):
        raise GameError("В городе нет жилья — постройте амбар/здания")
    c["pop"] += 1
    del s["units"][uid]
    refresh(s, owner)
    return f"Поселенец влился в {c['name']} (+1 👥)"


def available_items(s, owner, c):
    techs = s["players"][owner]["techs"]
    items = []
    res = resources_of(s, owner)
    for k, v in UNITS.items():
        if k == "missionary" and not s["players"][owner].get("religion"):
            continue                       # миссионеры — только у основателей религий
        if UNIT_RES.get(k) and res[UNIT_RES[k]] <= 0:
            continue                       # нет нужного ресурса
        if v.get("naval") and not coastal(s, c):
            continue                       # корабли строят только на побережье
        if not v["req"] or v["req"] in techs:
            items.append((f"unit:{k}", f"{v['name']} ⚔{v['att']} 🛡{v['def']}", v["cost"]))
    for k, v in BUILDINGS.items():
        if k not in c["buildings"] and (not v["req"] or v["req"] in techs):
            items.append((f"bld:{k}", v["name"], v["cost"]))
    for k, v in WONDERS.items():
        if k not in s["wonders"] and v["req"] in techs and c["pop"] >= 3:
            items.append((f"wnd:{k}", "🏛 " + v["name"], v["cost"]))
    return items


def set_build(s, owner, cid, item):
    c = own_city(s, owner, cid)
    if item not in [i[0] for i in available_items(s, owner, c)]:
        raise GameError("Это сейчас нельзя построить")
    c["build"] = item
    return "Приказ принят"


QUEUE_MAX = 5


def queue_add(s, owner, cid, item):
    """Добавляет объект в очередь производства города (если ничего не строится — начинает его)."""
    c = own_city(s, owner, cid)
    if item not in [i[0] for i in available_items(s, owner, c)]:
        raise GameError("Это сейчас нельзя построить")
    if not c["build"]:
        c["build"] = item
        return "Приказ принят"
    q = c.setdefault("queue", [])
    if len(q) >= QUEUE_MAX:
        raise GameError(f"Очередь полна (максимум {QUEUE_MAX})")
    if item.startswith(("bld:", "wnd:")) and (item == c["build"] or item in q):
        raise GameError("Это уже в очереди")
    q.append(item)
    return f"В очередь добавлено ({len(q)}/{QUEUE_MAX})"


def queue_clear(s, owner, cid):
    c = own_city(s, owner, cid)
    c["queue"] = []
    return "Очередь очищена"


def _next_in_queue(s, owner, c):
    """Берёт из очереди первый ещё доступный пункт (недоступные — пропускает)."""
    q = c.get("queue") or []
    ok = {i[0] for i in available_items(s, owner, c)}
    while q:
        it = q.pop(0)
        if it in ok and not (it.startswith("wnd:") and it.split(":")[1] in s["wonders"]):
            c["build"] = it
            return it
    return None


def buy(s, owner, cid):
    c = own_city(s, owner, cid)
    if not c["build"]:
        raise GameError("Сначала выберите, что строить")
    d = item_data(c["build"])
    if c["build"] == "unit:settler" and c["pop"] < 2:
        raise GameError("Для поселенца нужно население ≥ 2")
    missing = d["cost"] - c["prod"]
    if missing <= 0:
        raise GameError("Уже накоплено — будет готово в конце хода")
    price = 2 * missing
    p = s["players"][owner]
    if p["gold"] < price:
        raise GameError(f"Нужно {price}💰, у вас {p['gold']}")
    p["gold"] -= price
    c["prod"] = d["cost"]
    return f"Куплено за {price}💰 — будет готово в конце хода"


def buy_price(s, c):
    if not c["build"]:
        return None
    missing = item_data(c["build"])["cost"] - c["prod"]
    return 2 * missing if missing > 0 else None


def upgrade_price(frm, to):
    return max(10, 2 * (UNITS[to]["cost"] - UNITS[frm]["cost"]))


def upgrade_unit(s, owner, uid):
    """Улучшение юнита (как в Civ 6): технология, ресурс, своя территория, золото."""
    u = own_unit(s, owner, uid)
    to = UPGRADES.get(u["type"])
    if not to:
        raise GameError("Этот юнит нельзя улучшить")
    t = UNITS[to]
    if t["req"] and t["req"] not in s["players"][owner]["techs"]:
        raise GameError(f"Нужна технология «{TECHS[t['req']]['name']}»")
    if UNIT_RES.get(to) and resources_of(s, owner)[UNIT_RES[to]] <= 0:
        raise GameError(f"Нужен ресурс в вашей земле: {RESOURCES[UNIT_RES[to]]['name']}")
    if tile_owner(s, u["x"], u["y"]) != owner:
        raise GameError("Улучшать можно только на своей территории")
    if u.get("aboard"):
        raise GameError("Сначала высадите юнит")
    price = upgrade_price(u["type"], to)
    p = s["players"][owner]
    if p["gold"] < price:
        raise GameError(f"Нужно {price}💰, у вас {p['gold']}")
    p["gold"] -= price
    old = UNITS[u["type"]]["name"]
    u["type"], u["mv"], u["fort"], u["job"] = to, 0, False, None
    return f"⬆ {old} улучшен до «{UNITS[to]['name']}» (−{price}💰)"


def set_ready(s, owner):
    s["players"][owner]["ready"] = True
    return all_ready(s)


def all_ready(s):
    return all(p["ready"] for p in s["players"].values() if p["alive"])


# ---------- торговые пути ----------

def route_yield(s, r):
    """(золото, еда) в ход владельцу пути: тем дальше города, тем выгоднее."""
    a, b = s["cities"].get(r["a"]), s["cities"].get(r["b"])
    if not a or not b:
        return 0, 0
    d = dist((a["x"], a["y"]), (b["x"], b["y"]))
    return 2 + d // 3, 1 + d // 6


def route_dests(s, owner, uid):
    """Города, куда караван может открыть путь (стоит в своём городе, не в пути)."""
    u = s["units"].get(uid)
    if not u or u["owner"] != owner or u["type"] != "trader" or u["job"]:
        return []
    origin = city_at(s, u["x"], u["y"])
    if not origin or origin[1]["owner"] != owner:
        return []
    out = []
    for cid, c in s["cities"].items():
        if c["owner"] == owner and cid != origin[0]:
            g, f = route_yield(s, {"a": origin[0], "b": cid})
            out.append({"id": cid, "name": c["name"], "gold": g, "food": f})
    return sorted(out, key=lambda d: -(d["gold"] + d["food"]))


def start_route(s, owner, uid, cid):
    u = own_unit(s, owner, uid)
    if u["type"] != "trader":
        raise GameError("Торговый путь прокладывает только караван")
    if u["job"]:
        raise GameError("Караван уже в пути")
    origin = city_at(s, u["x"], u["y"])
    if not origin or origin[1]["owner"] != owner:
        raise GameError("Караван должен стоять в вашем городе")
    dest = own_city(s, owner, cid)
    if cid == origin[0]:
        raise GameError("Выберите другой город — путь открывается между разными городами")
    rid = _new_id(s)
    r = {"owner": owner, "a": origin[0], "b": cid, "left": TRADE_TURNS, "uid": uid}
    s.setdefault("routes", {})[rid] = r
    u["job"], u["left"], u["mv"] = "route", TRADE_TURNS, 0
    g, f = route_yield(s, r)
    return f"🐫 Путь открыт: {origin[1]['name']} → {dest['name']} (+{g}💰 +{f}🌾 в ход, {TRADE_TURNS} ходов)"


def cancel_route(s, owner, rid):
    r = s.get("routes", {}).get(str(rid))
    if not r or r["owner"] != owner:
        raise GameError("Такого торгового пути нет")
    u = s["units"].get(r["uid"])
    if u:
        u["job"], u["left"] = None, 0
    del s["routes"][rid]
    return "🐫 Караван отозван — путь закрыт"


# ---------- гражданские институты и строй ----------

def has_civic(s, owner, key):
    pl = s["players"].get(owner)
    return bool(pl) and key in pl.get("civics", [])


def culture_turn(s, owner):
    """Культура 🎭 в ход: сумма по городам (c['culture'] обновляется каждый ход)."""
    return sum(c.get("culture", 0) for c in s["cities"].values() if c["owner"] == owner)


def available_civics(s, owner):
    pl = s["players"][owner]
    done = pl.get("civics", [])
    return {k: c for k, c in CIVICS.items() if k not in done and all(r in done for r in c["req"])}


def set_civic(s, owner, key):
    if key not in available_civics(s, owner):
        raise GameError("Этот институт пока недоступен")
    s["players"][owner]["civic"] = key
    return f"🎭 Начинаем: «{CIVICS[key]['name']}» ({CIVICS[key]['cost']}🎭)"


def set_gov(s, owner, gov):
    pl = s["players"][owner]
    if "polphil" not in pl.get("civics", []):
        raise GameError("Сначала изучите институт «Политическая философия»")
    if gov not in GOVS:
        raise GameError("Неизвестный строй")
    pl["gov"] = gov
    return f"{GOVS[gov][0]} Новый строй: {GOVS[gov][1]} — {GOVS[gov][2]}"


def fortify(s, owner, uid):
    u = own_unit(s, owner, uid)
    if UNITS[u["type"]]["def"] == 0:
        raise GameError("Этот юнит не может укрепляться")
    u["fort"] = True
    u["job"] = None
    u["mv"] = 0
    return "🛡 Юнит укрепился (защита ×1.25, быстрее лечится)"


def _start_road(s, owner, u):
    if "wheel" not in s["players"][owner]["techs"]:
        raise GameError(f"Нужна технология «{TECHS['wheel']['name']}»")
    x, y = u["x"], u["y"]
    if s["map"][y][x] == "water":
        raise GameError("На воде дорогу не построить")
    if has_road(s, x, y):
        raise GameError("Здесь уже есть дорога")
    to = tile_owner(s, x, y)
    if to and to != owner:
        raise GameError("Это чужая территория")
    if u["mv"] <= 0:
        raise GameError("Юнит уже ходил в этом ходу")
    u["job"], u["left"], u["mv"] = "road", ROAD_TURNS, 0
    return f"Строится дорога ({ROAD_TURNS} хода)"


def start_job(s, owner, uid, job):
    u = own_unit(s, owner, uid)
    if u["type"] != "worker":
        raise GameError("Улучшения строят только рабочие")
    if job == "road":
        return _start_road(s, owner, u)
    if job not in IMPR:
        raise GameError("Неизвестное улучшение")
    im = IMPR[job]
    if im["req"] not in s["players"][owner]["techs"]:
        raise GameError(f"Нужна технология «{TECHS[im['req']]['name']}»")
    x, y = u["x"], u["y"]
    if s["map"][y][x] != im["on"]:
        raise GameError(f"{im['name']} строится на: {TERRAIN[im['on']]['name'].lower()}")
    to = tile_owner(s, x, y)
    if to and to != owner:
        raise GameError("Это чужая территория")
    if city_at(s, x, y) or f"{x},{y}" in s["impr"]:
        raise GameError("Здесь уже есть улучшение или город")
    if f"{x},{y}" in s.get("camps", []):
        raise GameError("Здесь лагерь варваров — сначала разорите его юнитом")
    if u["mv"] <= 0:
        raise GameError("Юнит уже ходил в этом ходу")
    turns = JOB_TURNS - (1 if has_civic(s, owner, "craft") else 0)   # «Ремесло»: на ход быстрее
    u["job"], u["left"], u["mv"] = job, turns, 0
    return f"Работа началась: {im['name']} ({turns} хода)"


def move_unit(s, owner, uid, d):
    u = own_unit(s, owner, uid)
    if u["mv"] <= 0:
        raise GameError("У юнита не осталось движения")
    if d not in DIRS:
        raise GameError("Неверное направление")
    x, y = u["x"] + DIRS[d][0], u["y"] + DIRS[d][1]
    if not (0 <= x < W and 0 <= y < H):
        raise GameError("Край карты")
    terr = TERRAIN[s["map"][y][x]]
    if UNITS[u["type"]].get("naval"):
        return _move_ship(s, owner, uid, u, x, y)
    if s["map"][y][x] == "water":
        return _board(s, owner, uid, u, x, y)
    if u.get("aboard") and (cs_at(s, x, y) or any(v["owner"] != owner for _, v in units_at(s, x, y))
                            or (city_at(s, x, y) and city_at(s, x, y)[1]["owner"] != owner)):
        raise GameError("Высадка возможна только на свободную клетку")
    cs = cs_at(s, x, y)
    if cs:
        if owner not in cs[1]["war"]:
            raise GameError(f"Город-государство «{cs[1]['name']}» закрыт для вас. "
                            "Подружитесь подарками или объявите войну (меню «Дипломатия»)")
        if UNITS[u["type"]]["att"] == 0:
            raise GameError("Этот юнит не может атаковать")
        u["fort"], u["job"] = False, None
        return _attack_cs(s, owner, uid, u, cs)
    if UNITS[u["type"]]["att"] > 0:
        to = tile_owner(s, x, y)
        if to and to != owner and relation(s, owner, to) != "war":
            raise GameError(f"Территория игрока {s['players'][to]['name']}: в мире боевые юниты "
                            "не пускают. Объявите войну (меню «Дипломатия»)")
    others = [(i, v) for i, v in units_at(s, x, y) if v["owner"] != owner]
    c = city_at(s, x, y)
    if c and c[1]["owner"] == owner:
        c = None
    owners = {v["owner"] for _, v in others} | ({c[1]["owner"]} if c else set())
    for o in owners:
        if relation(s, owner, o) != "war":
            raise GameError(f"С игроком {s['players'][o]['name']} мир. "
                            "Чтобы атаковать, объявите войну (меню «Дипломатия»)")
    u["fort"], u["job"] = False, None
    if others or c:
        return _attack(s, owner, uid, u, x, y, others, c)
    cost = ROAD_COST if has_road(s, u["x"], u["y"]) and has_road(s, x, y) else terr["cost"]
    u["x"], u["y"] = x, y
    u["mv"] = round(max(0, u["mv"] - cost), 2)
    if u.get("aboard"):
        u["aboard"], u["mv"] = None, 0
    refresh(s, owner)
    return (" ".join(t for t in (f"Перешли на ({x},{y})", _hut(s, owner, x, y),
                                 _camp(s, owner, x, y)) if t)).strip()


def _board(s, owner, uid, u, x, y):
    """Сухопутный юнит заходит на воду: только на свою галеру со свободным местом."""
    boat = next(((i, v) for i, v in units_at(s, x, y)
                 if v["owner"] == owner and UNITS[v["type"]].get("naval")), None)
    if not boat:
        raise GameError("Нельзя пройти по воде. Нужна своя галера рядом (постройте в прибрежном городе)")
    if u.get("aboard"):
        raise GameError("Юнит уже на борту — двигайте галеру")
    if _cargo(s, boat[0]) >= UNITS[boat[1]["type"]]["cap"]:
        raise GameError("На галере нет места (вмещает 2 юнита)")
    u["x"], u["y"], u["mv"], u["aboard"] = x, y, 0, boat[0]
    u["fort"], u["job"] = False, None
    refresh(s, owner)
    return "⛵ Погрузились на галеру"


def _move_ship(s, owner, uid, u, x, y):
    ut = UNITS[u["type"]]
    water = s["map"][y][x] == "water"
    town = city_at(s, x, y)
    others = [(i, v) for i, v in units_at(s, x, y) if v["owner"] != owner]
    if not water and not (town and town[1]["owner"] == owner):
        if cs_at(s, x, y):
            raise GameError("Корабли не могут нападать на города-государства")
        if not others and not (town and town[1]["owner"] != owner):
            raise GameError("Корабли ходят только по воде и в свои порты")
    owners = {v["owner"] for _, v in others} | ({town[1]["owner"]} if town and town[1]["owner"] != owner else set())
    for o in owners:
        if relation(s, owner, o) != "war":
            raise GameError(f"С игроком {s['players'][o]['name']} мир. Чтобы атаковать, объявите войну")
    if others or (town and town[1]["owner"] != owner):
        return _ship_attack(s, owner, uid, u, x, y, others, town, water)
    u["x"], u["y"] = x, y
    u["mv"] = round(max(0, u["mv"] - 1), 2)
    for v in s["units"].values():
        if v.get("aboard") == uid:
            v["x"], v["y"] = x, y
            if not water:
                v["aboard"] = None     # в порту пассажиры сходят на берег
    refresh(s, owner)
    return f"⛵ Плывём на ({x},{y})" + (" — порт, пассажиры сошли на берег" if not water else "")


def _ship_attack(s, owner, uid, u, x, y, others, town, water):
    ut = UNITS[u["type"]]
    u["mv"] = 0
    aname = s["players"][owner]["name"]
    if water:
        ships = [(i, v) for i, v in others if UNITS[v["type"]].get("naval")]
        if not ships:
            return "Здесь нет кораблей"
        did, d = max(ships, key=lambda t: UNITS[t[1]["type"]]["def"] * t[1]["hp"])
        if not _fight(s, ut["att"] * promo_mult(u), UNITS[d["type"]]["def"] * promo_mult(d), u, d):
            _kill_unit(s, uid)
            _news(s, d["owner"], f"🛡 Ваша галера ({x},{y}) отбила атаку игрока {aname}")
            return "⚔️ Ваш корабль потоплен"
        _kill_unit(s, did)
        _news(s, d["owner"], f"⚔️ Ваша галера потоплена игроком {aname} ({x},{y})")
        return "⚔️ Вражеский корабль потоплен!"
    mil = [(i, v) for i, v in others if UNITS[v["type"]]["def"] > 0]
    if not mil:
        if others:
            for i, v in others:
                _news(s, v["owner"], f"💀 Ваш {UNITS[v['type']]['name']} ({x},{y}) уничтожен с моря")
                s["units"].pop(i, None)
            return "⚔️ Береговые юниты уничтожены"
        raise GameError("С моря город без защитников не захватить — высадите войска")
    did, d = max(mil, key=lambda t: UNITS[t[1]["type"]]["def"] * t[1]["hp"])
    if not _fight(s, ut["att"] * promo_mult(u), _defense(s, d, x, y, town, u["type"]), u, d):
        _kill_unit(s, uid)
        _news(s, d["owner"], f"🛡 Ваш {UNITS[d['type']]['name']} ({x},{y}) отбил обстрел с моря")
        return "⚔️ Ваш корабль потоплен береговой обороной"
    _kill_unit(s, did)
    _news(s, d["owner"], f"⚔️ Ваш {UNITS[d['type']]['name']} погиб при обстреле с моря ({x},{y})")
    return "⚔️ Обстрел удался: защитник уничтожен"


def _fight(s, a, d, au, du):
    while au["hp"] > 0 and du["hp"] > 0:
        if random.random() < a / (a + d):
            du["hp"] -= 3
        else:
            au["hp"] -= 3
    xm = lambda unit: 2 if has_civic(s, unit.get("owner"), "milt") else 1   # «Военная традиция»: ×2 опыт
    au["xp"] = au.get("xp", 0) + (5 if du["hp"] <= 0 else 3) * xm(au)   # опыт за бой
    if du["hp"] > 0:
        du["xp"] = du.get("xp", 0) + 3 * xm(du)
    return au["hp"] > 0


def _attack_cs(s, owner, uid, u, cs):
    csid, c = cs
    u["mv"] = 0
    aname = s["players"][owner]["name"]
    if not _fight(s, UNITS[u["type"]]["att"] * promo_mult(u), (4 + s["turn"] // 10) * 1.25, u, {"hp": UNIT_HP}):
        del s["units"][uid]
        return f"⚔️ Ваш юнит погиб у стен «{c['name']}»"
    del s["cstates"][csid]
    cid = _new_id(s)
    s["cities"][cid] = {"owner": owner, "name": c["name"], "x": c["x"], "y": c["y"], "pop": 2,
                        "food": 0, "prod": 0, "build": None, "buildings": [], "wonders": [],
                        "capital": False, "culture": 0}
    u["x"], u["y"] = c["x"], c["y"]
    for k in c["inf"]:
        if k != owner:
            _news(s, k, f"🏴 Город-государство «{c['name']}» захвачен игроком {aname}")
    refresh(s, owner)
    return f"🏴 Город-государство «{c['name']}» захвачен и стал вашим городом!"


def _defense(s, d, x, y, c, atype):
    """Сила защиты юнита d на клетке (x, y); c — город на клетке (id, dict) или None."""
    dstr = UNITS[d["type"]]["def"] * TERRAIN[s["map"][y][x]]["def"] * promo_mult(d)
    if d["fort"]:
        dstr *= 1.25
    if c:
        dstr *= 1.25
        if "walls" in c[1]["buildings"] and atype != "catapult":
            dstr *= 1.5
        if city_level(c[1]) >= 3:
            dstr *= 1.15
        if s["players"][c[1]["owner"]].get("gov") == "monarchy":
            dstr *= 1.25          # «Монархия»: города держат оборону лучше
    return dstr


def _attack(s, owner, uid, u, x, y, enemy_units, c):
    ut = UNITS[u["type"]]
    if ut["att"] == 0:
        raise GameError("Этот юнит не может атаковать")
    u["mv"] = 0
    aname = s["players"][owner]["name"]
    mil = [(i, v) for i, v in enemy_units if UNITS[v["type"]]["def"] > 0]
    msg = ""
    if mil:
        did, d = max(mil, key=lambda t: UNITS[t[1]["type"]]["def"] * t[1]["hp"])
        dstr = _defense(s, d, x, y, c, u["type"])
        dname = UNITS[d["type"]]["name"]
        if not _fight(s, ut["att"] * promo_mult(u), dstr, u, d):
            del s["units"][uid]
            _news(s, d["owner"], f"🛡 Ваш {dname} ({x},{y}) отбил атаку игрока {aname}")
            return "⚔️ Ваш юнит погиб в бою"
        del s["units"][did]
        _news(s, d["owner"], f"⚔️ Ваш {dname} погиб при обороне ({x},{y}) от игрока {aname}")
        msg = "⚔️ Победа в бою! "
        if d["owner"] == "barb":
            s["players"][owner]["gold"] += BARB_BOUNTY
            msg = f"⚔️ Варвар повержен! +{BARB_BOUNTY}💰 "
        if any(UNITS[v["type"]]["def"] > 0 and i in s["units"] for i, v in enemy_units):
            return msg + "Но в клетке остались защитники"
    for i, v in enemy_units:
        if i in s["units"]:
            _news(s, v["owner"], f"💀 Ваш {UNITS[v['type']]['name']} ({x},{y}) уничтожен")
            del s["units"][i]
    if c:
        city = c[1]
        old = city["owner"]
        _news(s, old, f"🏴 Город {city['name']} захвачен игроком {aname}!")
        city["owner"] = owner
        city["pop"] = max(1, city["pop"] - 1)
        city["build"], city["prod"], city["queue"] = None, 0, []
        city["capital"] = False
        msg += f"🏴 Захвачен город {city['name']}!"
        refresh(s, old)
    u["x"], u["y"] = x, y
    refresh(s, owner)
    camp = _camp(s, owner, x, y)
    return ((msg + " " + camp).strip() if camp else msg) or "Клетка захвачена"


# ---------- дальний бой (как в Civ 6: без ответа, города берут только вблизи) ----------

def city_strength(s, c):
    """Сила обстрела города: растёт со временем, стены и уровень усиливают."""
    return (4 + s["turn"] // 10 + (2 if "walls" in c["buildings"] else 0)
            + (1 if city_level(c) >= 3 else 0))


def _ranged_dmg(a, dstr):
    return max(2, int(round(3 + 6 * a / (a + dstr))))


def ranged_attack(s, owner, uid, x, y):
    u = own_unit(s, owner, uid)
    ut = UNITS[u["type"]]
    if not ut.get("range"):
        raise GameError("Этот юнит бьёт только вблизи")
    if u["mv"] <= 0:
        raise GameError("Юнит уже ходил в этом ходу")
    if not 1 <= dist((u["x"], u["y"]), (x, y)) <= ut["range"]:
        raise GameError(f"Цель вне радиуса обстрела ({ut['range']})")
    targets = [(i, v) for i, v in units_at(s, x, y)
               if v["owner"] != owner and relation(s, owner, v["owner"]) == "war"]
    if not targets:
        raise GameError("В клетке нет вражеских юнитов")
    did, d = max(targets, key=lambda t: UNITS[t[1]["type"]]["def"] * t[1]["hp"])
    town = city_at(s, x, y)
    c = town if town and town[1]["owner"] == d["owner"] else None
    dmg = _ranged_dmg(ut["att"] * promo_mult(u), _defense(s, d, x, y, c, u["type"]))
    d["hp"] -= dmg
    u["mv"] = 0
    u["xp"] = u.get("xp", 0) + (4 if d["hp"] <= 0 else 2) * (2 if has_civic(s, u.get("owner"), "milt") else 1)
    dname = UNITS[d["type"]]["name"]
    aname = s["players"][owner]["name"]
    if d["hp"] <= 0:
        del s["units"][did]
        msg = f"🎯 {dname} уничтожен обстрелом!"
        if d["owner"] == "barb":
            s["players"][owner]["gold"] += BARB_BOUNTY
            msg += f" +{BARB_BOUNTY}💰"
        _news(s, d["owner"], f"💀 Ваш {dname} ({x},{y}) уничтожен обстрелом игрока {aname}")
    else:
        msg = f"🎯 Обстрел: {dname} −{dmg}❤ (осталось {d['hp']})"
        d["xp"] = d.get("xp", 0) + 2 * (2 if has_civic(s, d.get("owner"), "milt") else 1)
        _news(s, d["owner"], f"🎯 Ваш {dname} ({x},{y}) обстрелен игроком {aname}: −{dmg}❤")
    return msg


def city_strike(s, owner, cid, x, y):
    c = own_city(s, owner, cid)
    if c.get("struck") == s["turn"]:
        raise GameError("Город уже стрелял в этом ходу")
    if not 1 <= dist((c["x"], c["y"]), (x, y)) <= 2:
        raise GameError("Цель вне радиуса обстрела города (2)")
    targets = [(i, v) for i, v in units_at(s, x, y)
               if v["owner"] != owner and relation(s, owner, v["owner"]) == "war"]
    if not targets:
        raise GameError("В клетке нет вражеских юнитов")
    did, d = max(targets, key=lambda t: UNITS[t[1]["type"]]["def"] * t[1]["hp"])
    dstr = UNITS[d["type"]]["def"] * TERRAIN[s["map"][y][x]]["def"] * (1.25 if d["fort"] else 1)
    dmg = _ranged_dmg(city_strength(s, c), dstr)
    d["hp"] -= dmg
    c["struck"] = s["turn"]
    if d["hp"] > 0:
        d["xp"] = d.get("xp", 0) + 2 * (2 if has_civic(s, d.get("owner"), "milt") else 1)
    dname = UNITS[d["type"]]["name"]
    if d["hp"] <= 0:
        del s["units"][did]
        msg = f"🎯 {c['name']}: {dname} уничтожен!"
        if d["owner"] == "barb":
            s["players"][owner]["gold"] += BARB_BOUNTY
            msg += f" +{BARB_BOUNTY}💰"
        _news(s, d["owner"], f"💀 Ваш {dname} ({x},{y}) уничтожен обстрелом из города {c['name']}")
    else:
        msg = f"🎯 {c['name']}: {dname} −{dmg}❤ (осталось {d['hp']})"
        _news(s, d["owner"], f"🎯 Ваш {dname} ({x},{y}) обстрелен из города {c['name']}: −{dmg}❤")
    return msg


# ---------- ход ----------

ROAD_LINK_GOLD = 2     # золото за город, соединённый дорогой со столицей


def road_connected(s, c):
    """Соединён ли город дорогами (клетки с дорогами и свои города) со столицей владельца."""
    if c["capital"]:
        return False
    cap = next((q for q in s["cities"].values() if q["owner"] == c["owner"] and q["capital"]), None)
    if not cap:
        return False
    goal, start = (cap["x"], cap["y"]), (c["x"], c["y"])
    seen, stack = {start}, [start]
    while stack:
        cur = stack.pop()
        if cur == goal:
            return True
        for dx, dy in DIRS.values():
            n = (cur[0] + dx, cur[1] + dy)
            if n in seen or not (0 <= n[0] < W and 0 <= n[1] < H):
                continue
            town = city_at(s, *n)
            if f"{n[0]},{n[1]}" in s.get("roads", []) or (town and town[1]["owner"] == c["owner"]):
                seen.add(n)
                stack.append(n)
    return False


def locked_units(s, owner):
    """Юниты, для которых изучена технология, но нет ресурса: [(название, эмодзи, ресурс)]."""
    techs = s["players"][owner]["techs"]
    res = resources_of(s, owner)
    return [(v["name"], RESOURCES[UNIT_RES[k]]["emoji"], RESOURCES[UNIT_RES[k]]["name"])
            for k, v in UNITS.items()
            if UNIT_RES.get(k) and res[UNIT_RES[k]] <= 0 and (not v["req"] or v["req"] in techs)]


def city_level(c):
    lvl = 1
    for i, (th, _) in enumerate(CITY_LEVELS):
        if c["pop"] >= th:
            lvl = i + 1
    return lvl


def city_level_name(c):
    return CITY_LEVELS[city_level(c) - 1][1]


def city_yields(s, c):
    """(еда, производство, наука, золото) города."""
    pl = s["players"][c["owner"]]
    f, p = tile_yield(s, c["x"], c["y"])
    f, p = max(f, 2), max(p, 1)
    tiles = []
    owners = tile_owners(s)
    for dy in range(-2, 3):
        for dx in range(-2, 3):
            x, y = c["x"] + dx, c["y"] + dy
            if (dx or dy) and 0 <= x < W and 0 <= y < H and not city_at(s, x, y) \
                    and not cs_at(s, x, y) and tile_owner(s, x, y, owners) in (None, c["owner"]):
                tiles.append(tile_yield(s, x, y))
    tiles.sort(key=lambda t: t[0] * 1.5 + t[1], reverse=True)
    for tf, tp in tiles[:c["pop"]]:
        f += tf
        p += tp
    sci = c["pop"]
    gold = 1 + c["pop"] // 2
    if "granary" in c["buildings"]:
        f += 2
    if "library" in c["buildings"]:
        sci += 3
    if "market" in c["buildings"]:
        gold += 3
    if "workshop" in c["buildings"]:
        p += 2
    if "gardens" in c["wonders"]:
        f += 3
    if "pyramids" in c["wonders"]:
        p += 3
    if "library" in c["wonders"]:
        sci += 4
    if "colossus" in c["wonders"]:
        gold += 5
    b = _belief(s, c)
    if b == "fertility":
        f += 2
    elif b == "wisdom":
        sci += 2
    elif b == "wealth":
        gold += 2
    lvl = city_level(c)
    if lvl >= 2:            # Город: +1⚙️ +1💰
        p += 1
        gold += 1
    if lvl >= 3:            # Мегаполис: ещё +1⚙️ +1💰 +2🔬
        p += 1
        gold += 1
        sci += 2
    if c["capital"]:
        p += 1
        sci += 1
    if "philosophy" in pl["techs"]:
        sci += 1
    civ = pl.get("civics", [])
    if "code" in civ and c["capital"]:
        gold += 1
    gov = pl.get("gov")
    if gov == "autocracy":
        p += 1
    elif gov == "monarchy":
        gold += 1
    elif gov == "republic":
        sci += 2
    if road_connected(s, c):
        gold += ROAD_LINK_GOLD
    my_cid = next((i for i, cc in s["cities"].items() if cc is c), None)
    if my_cid:
        for pos, key in s.get("nwonders", {}).items():
            x, y = map(int, pos.split(","))
            if owners.get((x, y)) == my_cid:
                gold += NWONDERS[key].get("gold", 0)
    return f, p, sci, gold


def income(s, k):
    return sum(city_yields(s, c)[3] for c in s["cities"].values() if c["owner"] == k)


def food_need(c):
    return 6 + c["pop"] * 3


def housing(s, c):
    """Жильё: рост населения остановлен на лимите (как в Civ 6)."""
    return (2 + (2 if "granary" in c["buildings"] else 0) + (1 if coastal(s, c) else 0)
            + (1 if "games" in s["players"][c["owner"]].get("civics", []) else 0))


def score(s, k):
    cs = [c for c in s["cities"].values() if c["owner"] == k]
    p = s["players"][k]
    return (10 * len(cs) + 2 * sum(c["pop"] for c in cs) + 5 * len(p["techs"])
            + WONDER_SCORE * sum(len(c["wonders"]) for c in cs) + p["gold"] // 20
            + sum(c.get("culture", 0) for c in cs) // 10
            + 2 * sum(1 for c in s["cities"].values() if p.get("religion") and c.get("religion") == p["religion"])
            + 5 * sum(1 for q in s.get("cstates", {}).values() if q.get("ally") == k))


def _belief(s, c):
    rel = s.get("religions", {}).get(c.get("religion"))
    return rel["belief"] if rel else None


def can_found_religion(s, k):
    p = s["players"][k]
    return (not p.get("religion") and p.get("faith", 0) >= FAITH_NEED
            and len(s.get("religions", {})) < len(RELIGION_NAMES)
            and any(c["owner"] == k and "temple" in c["buildings"] for c in s["cities"].values()))


def found_religion(s, k, belief):
    """Основать религию. Возвращает (сообщение, публичное объявление)."""
    if belief not in BELIEFS:
        raise GameError("Неизвестное верование")
    if not can_found_religion(s, k):
        raise GameError(f"Нужно {FAITH_NEED} веры и храм в одном из городов, а религии в мире ещё есть свободные")
    rels = s.setdefault("religions", {})
    rid = next(str(i) for i in range(len(RELIGION_NAMES)) if str(i) not in rels)
    holy = next((cid for cid, c in s["cities"].items() if c["owner"] == k and "temple" in c["buildings"]))
    rels[rid] = {"name": RELIGION_NAMES[int(rid)], "founder": k, "belief": belief, "holy": holy}
    s["cities"][holy]["religion"] = rid
    p = s["players"][k]
    p["religion"] = rid
    p["faith"] -= FAITH_NEED
    return (f"Основана религия «{RELIGION_NAMES[int(rid)]}»",
            f"🕊 {p['name']} основал религию «{RELIGION_NAMES[int(rid)]}» ({BELIEFS[belief][1]}) "
            f"в городе {s['cities'][holy]['name']}!")


def preach_targets(s, owner, uid):
    """Города рядом с миссионером, которые он может обратить: [(id города, город)]."""
    u = s["units"].get(uid)
    rid = s["players"][owner].get("religion")
    if not u or u["type"] != "missionary" or not rid:
        return []
    rels = s.get("religions", {})
    out = []
    for cid, c in s["cities"].items():
        cur = c.get("religion")
        if dist((u["x"], u["y"]), (c["x"], c["y"])) <= 1 and cur != rid \
                and not (cur and rels.get(cur, {}).get("holy") == cid):
            out.append((cid, c))
    return out


def preach(s, owner, uid, cid):
    """Миссионер обращает город рядом с собой в веру владельца (миссионер расходуется)."""
    u = own_unit(s, owner, uid)
    if u["type"] != "missionary":
        raise GameError("Проповедовать могут только миссионеры")
    rid = s["players"][owner].get("religion")
    if not rid:
        raise GameError("У вас нет религии")
    c = s["cities"].get(cid)
    if not c:
        raise GameError("Город не найден")
    if dist((u["x"], u["y"]), (c["x"], c["y"])) > 1:
        raise GameError("Подойдите к городу вплотную")
    if c.get("religion") == rid:
        raise GameError("Город уже исповедует вашу веру")
    cur = c.get("religion")
    if cur and s["religions"][cur]["holy"] == cid:
        raise GameError("Священный город другой веры обратить нельзя")
    name = s["religions"][rid]["name"]
    c["religion"] = rid
    del s["units"][uid]
    if c["owner"] != owner:
        _news(s, c["owner"], f"🕊 Миссионер игрока {s['players'][owner]['name']} обратил {c['name']} в веру «{name}»")
    return f"📿 {c['name']} принял веру «{name}»"


def religion_share(s):
    """{id религии: (городов верующих, всего городов)}."""
    total = len(s["cities"])
    return {rid: (sum(1 for c in s["cities"].values() if c.get("religion") == rid), total)
            for rid in s.get("religions", {})}


def _religion_hold(s, pub):
    """Религиозная победа: религия держит ≥60% городов (при ≥6 городах) REL_WIN_TURNS ходов подряд.
    Возвращает id победителя или None."""
    hold = s.setdefault("rel_hold", {})
    lead = None
    for rid, (n, total) in religion_share(s).items():
        founder = s["religions"][rid]["founder"]
        if total >= REL_WIN_MIN_CITIES and n / total >= REL_WIN_SHARE and s["players"][founder]["alive"]:
            lead = rid
    if not lead:
        if hold:
            pub.append("🕊 Религия потеряла большинство — религиозная победа отменяется")
            hold.clear()
        return None
    rel = s["religions"][lead]
    if hold.get("rid") != lead:
        hold.clear()
        hold.update({"rid": lead, "n": 0})
        pub.append(f"🕊 Религию «{rel['name']}» исповедует не меньше {int(REL_WIN_SHARE * 100)}% городов! "
                   f"Если так продержится {REL_WIN_TURNS} хода, {s['players'][rel['founder']]['name']} победит")
    hold["n"] += 1
    return rel["founder"] if hold["n"] >= REL_WIN_TURNS else None


def _spread_religion(s):
    rels = s.get("religions", {})
    if not rels:
        return
    src = {cid: c.get("religion") for cid, c in s["cities"].items()}
    for cid, c in s["cities"].items():
        rid = src[cid]
        if not rid:
            continue
        for cid2, c2 in s["cities"].items():
            if cid2 == cid or dist((c["x"], c["y"]), (c2["x"], c2["y"])) > SPREAD_RANGE:
                continue
            r2 = c2.get("religion")
            if r2 == rid or (r2 and rels[r2]["holy"] == cid2):
                continue
            if random.random() < (0.25 if not r2 else 0.05):
                c2["religion"] = rid
                _news(s, c2["owner"], f"🕊 В городе {c2['name']} распространилась вера «{rels[rid]['name']}»")


def _camp(s, owner, x, y):
    """Разорение лагеря варваров при входе в его клетку. Возвращает текст или ''."""
    key = f"{x},{y}"
    camps = s.setdefault("camps", [])
    if key not in camps:
        return ""
    camps.remove(key)
    s["players"][owner]["gold"] += BARB_CAMP_GOLD
    return f"🏕 Лагерь варваров разорён! +{BARB_CAMP_GOLD}💰"


def _hut(s, owner, x, y):
    """Награда за вход в селение. Возвращает текст (или пустую строку)."""
    huts = s.setdefault("huts", [])
    key = f"{x},{y}"
    if key not in huts:
        return ""
    huts.remove(key)
    p = s["players"][owner]
    r = random.random()
    if r < 0.30:
        p["gold"] += 30
        return "🛖 Селение: +30💰!"
    if r < 0.55:
        if p["research"]:
            p["progress"] += 25
            return "🛖 Мудрецы селения: +25🔬 к исследованию!"
        p["gold"] += 25
        return "🛖 Селение: +25💰!"
    if r < 0.75:
        spawn(s, owner, "warrior", x, y)
        return "🛖 К вам присоединился воин!"
    if r < 0.90:
        seen = p["seen"]
        for yy in range(max(0, y - 4), min(H, y + 5)):
            for xx in range(max(0, x - 4), min(W, x + 5)):
                seen[yy * W + xx] = 1
        return "🛖 Старейшины показали окрестности!"
    free = [(x + dx, y + dy) for dx, dy in DIRS.values()
            if 0 <= x + dx < W and 0 <= y + dy < H and s["map"][y + dy][x + dx] != "water"
            and not units_at(s, x + dx, y + dy) and not city_at(s, x + dx, y + dy)]
    if free:
        bx, by = random.choice(free)
        spawn(s, "barb", "warrior", bx, by)
        return "🛖 Засада варваров!"
    p["gold"] += 15
    return "🛖 Селение: +15💰"


def _step_toward(s, start, goal):
    """Первый шаг по суше от start к goal (поиск в ширину); None, если пути нет."""
    if start == goal:
        return None
    prev = {start: None}
    q = [start]
    while q:
        cur = q.pop(0)
        if cur == goal:
            break
        for dx, dy in DIRS.values():
            n = (cur[0] + dx, cur[1] + dy)
            if n in prev or not (0 <= n[0] < W and 0 <= n[1] < H) or s["map"][n[1]][n[0]] == "water" or cs_at(s, n[0], n[1]):
                continue
            prev[n] = cur
            q.append(n)
    if goal not in prev:
        return None
    cur = goal
    while prev[cur] != start:
        cur = prev[cur]
    return cur


def _barb_move(s, uid, u, nxt):
    """Шаг варвара. True — можно идти дальше, False — ход закончен."""
    x, y = nxt
    others = [(i, v) for i, v in units_at(s, x, y) if v["owner"] != "barb"]
    c = city_at(s, x, y)
    if c and c[1]["owner"] not in s["players"]:
        c = None
    if not (others or c):
        u["x"], u["y"] = x, y
        return True
    mil = [(i, v) for i, v in others if UNITS[v["type"]]["def"] > 0]
    if mil:
        did, d = max(mil, key=lambda t: UNITS[t[1]["type"]]["def"] * t[1]["hp"])
        dname = UNITS[d["type"]]["name"]
        if not _fight(s, UNITS[u["type"]]["att"] * promo_mult(u), _defense(s, d, x, y, c, u["type"]), u, d):
            del s["units"][uid]
            _news(s, d["owner"], f"🛡 Ваш {dname} ({x},{y}) отбил нападение варваров")
            return False
        del s["units"][did]
        _news(s, d["owner"], f"⚔️ Варвары убили ваш {dname} ({x},{y})")
        if any(UNITS[v["type"]]["def"] > 0 and i in s["units"] for i, v in others):
            return False
    for i, v in others:
        if i in s["units"]:
            _news(s, v["owner"], f"💀 Варвары уничтожили ваш {UNITS[v['type']]['name']} ({x},{y})")
            del s["units"][i]
    if c:
        city = c[1]
        loot = min(10, s["players"][city["owner"]]["gold"])
        s["players"][city["owner"]]["gold"] -= loot
        city["pop"] = max(1, city["pop"] - 1)
        city["prod"] = 0
        _news(s, city["owner"], f"🔥 Варвары разграбили {city['name']}: −{loot}💰, −1 жителя")
        del s["units"][uid]
        return False
    u["x"], u["y"] = x, y
    return False


def _barbarians(s):
    cities = [(c["x"], c["y"]) for c in s["cities"].values()
              if c["owner"] in s["players"] and s["players"][c["owner"]]["alive"]]
    if not cities:
        return
    for uid in [i for i, u in s["units"].items() if u["owner"] == "barb"]:
        u = s["units"].get(uid)
        for _ in range(UNITS[u["type"]]["moves"] if u else 0):
            pos = (u["x"], u["y"])
            nxt = _step_toward(s, pos, min(cities, key=lambda cc: dist(pos, cc)))
            if nxt is None or not _barb_move(s, uid, u, nxt) or uid not in s["units"]:
                break


def _barb_type(s):
    if s["turn"] < 20:
        return "warrior"
    if s["turn"] < 32:
        return random.choice(["warrior", "archer"])
    return random.choice(["archer", "horseman", "swordsman"])


def _spawn_barbarians(s):
    if s["turn"] < 8:
        return
    alive = [k for k, p in s["players"].items() if p["alive"]]
    cur = sum(1 for u in s["units"].values() if u["owner"] == "barb")
    if cur >= min(6, 1 + s["turn"] // 12 + len(alive) // 2):
        return
    camps = s.get("camps", [])
    if camps and random.random() < 0.6:          # волны из лагерей (как в Civ 6)
        for key in random.sample(camps, min(len(camps), 2)):
            x, y = map(int, key.split(","))
            if not units_at(s, x, y) and not city_at(s, x, y):
                spawn(s, "barb", _barb_type(s), x, y)
                return
    if random.random() > 0.4:
        return
    vis = set()
    for k in alive:
        vis |= visible(s, k)
    cities = [(c["x"], c["y"]) for c in s["cities"].values()]
    mine = [(u["x"], u["y"]) for u in s["units"].values() if u["owner"] != "barb"]
    cands = [(x, y) for y in range(H) for x in range(W)
             if s["map"][y][x] != "water" and (x, y) not in vis
             and all(dist((x, y), q) >= 4 for q in cities) and all(dist((x, y), q) >= 3 for q in mine)]
    if not cands:
        return
    x, y = random.choice(cands)
    spawn(s, "barb", _barb_type(s), x, y)


def disband(s, owner, uid):
    own_unit(s, owner, uid)
    del s["units"][uid]
    return "Юнит распущен"


def process_turn(s):
    """Смена хода. Возвращает список публичных событий; личные — в players[k]['news']."""
    pub = []
    for p in s["players"].values():
        p["news"] = []
    sci_total = {k: 0 for k in s["players"]}
    gold_total = {k: 0 for k in s["players"]}
    for cid, c in s["cities"].items():
        owner = c["owner"]
        f, p, sci, g = city_yields(s, c)
        m = ai_mult(s, owner)
        if m != 1.0:
            p, sci, g = max(1, round(p * m)), round(sci * m), round(g * m)
        sci_total[owner] += sci
        gold_total[owner] += g
        if c["pop"] < housing(s, c):
            c["food"] = max(0, c["food"] + f - 2 * c["pop"])
            if c["food"] >= food_need(c):
                old_lvl = city_level(c)
                c["pop"] += 1
                c["food"] = 0
                _news(s, owner, f"📈 {c['name']} вырос до {c['pop']}")
                if city_level(c) > old_lvl:
                    _news(s, owner, f"🎉 {c['name']} теперь {city_level_name(c)} — новые бонусы!")
        else:
            c["food"] = min(c["food"], food_need(c) - 1)   # рост сдержан жильём
        c["prod"] += p
        old_r = border_radius(c)
        pl_o = s["players"][owner]
        c["culture"] = (c.get("culture", 0) + 1 + c["pop"] // 2 + (2 if "temple" in c["buildings"] else 0)
                        + 3 * len(c["wonders"]) + (1 if c["capital"] else 0)
                        + (2 if "games" in pl_o.get("civics", []) else 0)
                        + (1 if pl_o.get("gov") == "republic" else 0))
        if _belief(s, c) == "fervor":
            c["culture"] = c.get("culture", 0) + 2
        if border_radius(c) > old_r:
            _news(s, owner, f"🗺 Границы города {c['name']} расширились")
        b = c["build"]
        if not b:
            continue
        kind, key = b.split(":")
        d = item_data(b)
        if kind == "wnd" and key in s["wonders"]:
            c["build"] = None
            if _next_in_queue(s, owner, c):
                _news(s, owner, f"🏛 {d['name'].split(' (')[0]} уже построено другой цивилизацией — {c['name']} берёт следующее из очереди")
            else:
                _news(s, owner, f"🏛 {d['name'].split(' (')[0]} уже построено другой цивилизацией — выберите новое производство в {c['name']}")
        elif c["prod"] >= d["cost"] and not (key == "settler" and c["pop"] < 2):
            c["prod"] -= d["cost"]
            c["build"] = None
            nm = d["name"].split(" (")[0]
            if kind == "unit":
                if key == "settler":
                    c["pop"] -= 1
                _spawn_at(s, owner, key, c)
            elif kind == "bld":
                c["buildings"].append(key)
            else:
                c["wonders"].append(key)
                s["wonders"][key] = cid
                pub.append(f"🏛 {s['players'][owner]['name']} построил чудо света «{nm}» в городе {c['name']}!")
            _news(s, owner, f"🔨 {c['name']}: готово — {nm}")
            nxt = _next_in_queue(s, owner, c)
            if nxt:
                _news(s, owner, f"📋 {c['name']}: из очереди — {item_data(nxt)['name'].split(' (')[0]}")
    for rid, r in list(s.get("routes", {}).items()):        # торговые пути
        owner = r["owner"]
        a, b = s["cities"].get(r["a"]), s["cities"].get(r["b"])
        u = s["units"].get(r["uid"])
        if not a or not b or not u or owner not in gold_total:
            if u:
                u["job"], u["left"] = None, 0
            s["routes"].pop(rid, None)
            if a:
                _news(s, owner, f"🐫 Торговый путь из {a['name']} закрылся")
            continue
        g, f = route_yield(s, r)
        gold_total[owner] += g
        if a["pop"] < housing(s, a):
            a["food"] += f
        r["left"] -= 1
        u["left"] = r["left"]
        if r["left"] <= 0:
            del s["routes"][rid]
            u["job"], u["left"] = None, 0
            u["x"], u["y"] = a["x"], a["y"]
            _news(s, owner, f"🐫 Караван вернулся в {a['name']} — путь завершён, можно открыть новый")
    for csid, cs in s.get("cstates", {}).items():
        for k in list(cs["inf"]):
            cs["inf"][k] = max(0, cs["inf"][k] - 1)
        ally = cs_ally(cs)
        if ally != cs.get("ally"):
            if cs.get("ally"):
                _news(s, cs["ally"], f"🤝 Вы потеряли союз с «{cs['name']}»")
            if ally:
                _news(s, ally, f"🤝 «{cs['name']}» теперь ваш союзник!")
            cs["ally"] = ally
        if ally and s["players"][ally]["alive"]:
            if cs["kind"] == "trade":
                gold_total[ally] += 3 + (2 if has_civic(s, ally, "diplom") else 0)
            elif cs["kind"] == "science":
                sci_total[ally] += 3
            elif cs["kind"] == "military" and s["turn"] % 8 == 0:
                mine = [c for c in s["cities"].values() if c["owner"] == ally]
                if mine:
                    spawn(s, ally, "warrior", mine[0]["x"], mine[0]["y"])
                    _news(s, ally, f"🪖 «{cs['name']}» прислал вам воина")
    for k, pl in s["players"].items():       # самоцветы, вера, религии
        if pl["alive"]:
            gold_total[k] += GEM_GOLD * resources_of(s, k)["gems"]
    owners_nw = tile_owners(s)
    cid_of = {id(c): i for i, c in s["cities"].items()}
    for c in s["cities"].values():
        pl = s["players"][c["owner"]]
        extra_faith = sum(NWONDERS[k].get("faith", 0) for pos, k in s.get("nwonders", {}).items()
                          if owners_nw.get(tuple(map(int, pos.split(",")))) == cid_of[id(c)])
        pl["faith"] = pl.get("faith", 0) + 1 + (2 if "temple" in c["buildings"] else 0) \
            + 3 * len(c["wonders"]) + extra_faith
    _spread_religion(s)
    for rid, rel in s.get("religions", {}).items():
        foreign = sum(1 for c in s["cities"].values() if c.get("religion") == rid and c["owner"] != rel["founder"])
        if foreign and rel["founder"] in gold_total:
            gold_total[rel["founder"]] += foreign
    for k, pl in s["players"].items():
        pl["gold"] += gold_total[k]
        if pl["alive"]:                                  # культура → институты
            pl["cprogress"] = pl.get("cprogress", 0) + culture_turn(s, k)
            cv = pl.get("civic")
            if cv and cv in CIVICS and pl["cprogress"] >= CIVICS[cv]["cost"]:
                pl["cprogress"] -= CIVICS[cv]["cost"]
                pl.setdefault("civics", []).append(cv)
                pl["civic"] = None
                _news(s, k, f"🎭 Институт принят: «{CIVICS[cv]['name']}» — {CIVICS[cv]['note']}")
        if pl["alive"] and pl["research"]:
            pl["progress"] += sci_total[k]
            t = TECHS[pl["research"]]
            if pl["progress"] >= t["cost"]:
                pl["progress"] -= t["cost"]
                pl["techs"].append(pl["research"])
                _news(s, k, f"🔬 Изучено: «{t['name']}»")
                pl["research"] = None
        elif pl["alive"] and available_techs(s, k):
            _news(s, k, "🔬 Наука простаивает — выберите технологию!")
    for u in s["units"].values():
        if u["job"] and u["job"] != "route":      # «route» обсчитывается в блоке торговых путей
            u["left"] -= 1
            if u["left"] <= 0:
                if u["job"] == "road":
                    s.setdefault("roads", []).append(f"{u['x']},{u['y']}")
                else:
                    s["impr"][f"{u['x']},{u['y']}"] = u["job"]
                nm, em = job_info(u["job"])
                _news(s, u["owner"], f"{em} {nm} построена ({u['x']},{u['y']})")
                u["job"] = None
        home = city_at(s, u["x"], u["y"])
        in_city = bool(home) and home[1]["owner"] == u["owner"]
        u["hp"] = min(UNIT_HP, u["hp"] + 2 + (2 if (u["fort"] or in_city) else 0))
        u["mv"] = 0 if u["job"] else UNITS[u["type"]]["moves"]
    _barbarians(s)
    _spawn_barbarians(s)
    for k, pl in s["players"].items():
        if not pl["alive"]:
            continue
        has_city = any(c["owner"] == k for c in s["cities"].values())
        has_settler = any(u["owner"] == k and u["type"] == "settler" for u in s["units"].values())
        if not has_city and not has_settler:
            pl["alive"] = False
            pub.append(f"💀 {pl['name']} выбыл из игры")
            for i in [i for i, u in s["units"].items() if u["owner"] == k]:
                del s["units"][i]
    for k, pl in s["players"].items():
        pl["ready"] = False
        if pl["alive"]:
            refresh(s, k)
    s["turn"] += 1
    alive = [k for k, p in s["players"].items() if p["alive"]]
    sci_win = [k for k in alive if len(s["players"][k]["techs"]) == len(TECHS)]
    rel_win = _religion_hold(s, pub)
    if sci_win:
        s["winner"], s["win_reason"] = max(sci_win, key=lambda k: score(s, k)), "science"
    elif rel_win:
        s["winner"], s["win_reason"] = rel_win, "religion"
    elif not alive:
        s["winner"], s["win_reason"] = "none", "domination"
    elif len(s["players"]) > 1 and len(alive) == 1:
        s["winner"], s["win_reason"] = alive[0], "domination"
    elif any(not s["players"][k].get("ai") for k in s["players"]) and \
            not any(not s["players"][k].get("ai") for k in alive):
        s["winner"], s["win_reason"] = max(alive, key=lambda k: score(s, k)), "domination"
    elif s["turn"] > MAX_TURNS:
        s["winner"], s["win_reason"] = max(alive, key=lambda k: score(s, k)), "score"
    return pub


# ---------- отображение ----------

def render_map(s, viewer, hl=None):
    vis = visible(s, viewer)
    seen = s["players"][viewer]["seen"]
    rows = []
    for y in range(H):
        row = ""
        for x in range(W):
            if hl == (x, y):
                row += "⭐"
            elif not seen[y * W + x]:
                row += "⬛"
            elif (x, y) in vis:
                c = city_at(s, x, y)
                us = units_at(s, x, y)
                if c:
                    row += SQUARES[s["players"][c[1]["owner"]]["color"]]
                elif cs_at(s, x, y):
                    row += "🏯"
                elif us:
                    o = us[0][1]["owner"]
                    row += BARB if o == "barb" else CIRCLES[s["players"][o]["color"]]
                elif f"{x},{y}" in s.get("huts", []):
                    row += "🛖"
                elif f"{x},{y}" in s.get("camps", []):
                    row += "🏕"
                elif f"{x},{y}" in s.get("nwonders", {}):
                    row += NWONDERS[s["nwonders"][f"{x},{y}"]]["emoji"]
                else:
                    im = s["impr"].get(f"{x},{y}")
                    rs = s.get("res", {}).get(f"{x},{y}")
                    row += (IMPR[im]["emoji"] if im else RESOURCES[rs]["emoji"] if rs
                            else TERRAIN[s["map"][y][x]]["emoji"])
            else:
                row += "🏯" if cs_at(s, x, y) else TERRAIN[s["map"][y][x]]["emoji"]
        rows.append(row)
    return "\n".join(rows)


def legend(s):
    lines = []
    for k, p in s["players"].items():
        st = " 💀" if not p["alive"] else ""
        bot = " 🤖" if p.get("ai") else ""
        lines.append(f"{SQUARES[p['color']]}{CIRCLES[p['color']]} {p['name']}{bot} — очки {score(s, k)}{st}")
    return "\n".join(lines)




def view(s, k):
    """Состояние для клиента Mini App: только то, что игрок вправе видеть."""
    vis = visible(s, k)
    seen = s["players"][k]["seen"]
    known = lambda x, y: bool(seen[y * W + x])
    pos = lambda key: tuple(map(int, key.split(",")))
    pl = s["players"][k]

    def city_pub(i, c):
        d = {"id": i, "x": c["x"], "y": c["y"], "name": c["name"],
             "owner": c["owner"], "pop": c["pop"], "capital": c["capital"],
             "culture": c.get("culture", 0), "religion": c.get("religion")}
        if c["owner"] == k:
            d.update(build=c["build"], queue=list(c.get("queue") or []), prod=c["prod"], buildings=c["buildings"],
                     wonders=c["wonders"], food=c["food"], yields=city_yields(s, c),
                     buy=buy_price(s, c), struck=c.get("struck") == s["turn"],
                     strength=city_strength(s, c), housing=housing(s, c))
        return d

    return {
        "you": k, "turn": s["turn"], "w": W, "h": H, "winner": s["winner"],
        "win_reason": s["win_reason"],
        "tiles": [[s["map"][y][x] if known(x, y) else None for x in range(W)] for y in range(H)],
        "visible": sorted(vis),
        "owners": {f"{x},{y}": s["cities"][cid]["owner"]
                   for (x, y), cid in tile_owners(s).items() if known(x, y)},
        "res": {p: r for p, r in s.get("res", {}).items() if known(*pos(p))},
        "impr": {p: r for p, r in s["impr"].items() if known(*pos(p))},
        "huts": [p for p in s.get("huts", []) if known(*pos(p))],
        "camps": [p for p in s.get("camps", []) if known(*pos(p))],
        "nwonders": {p: k for p, k in s.get("nwonders", {}).items() if known(*pos(p))},
        "roads": [p for p in s.get("roads", []) if known(*pos(p))],
        "cities": [city_pub(i, c) for i, c in s["cities"].items()
                   if (c["x"], c["y"]) in vis or c["owner"] == k],
        "units": [{"id": i, **u} for i, u in s["units"].items()
                  if (u["x"], u["y"]) in vis or u["owner"] == k],
        "cstates": [{"id": i, "name": c["name"], "x": c["x"], "y": c["y"], "kind": c["kind"],
                    "inf": c["inf"].get(k, 0), "ally": c.get("ally"), "war": k in c["war"]}
                    for i, c in s.get("cstates", {}).items() if known(c["x"], c["y"])],
        "routes": [{"id": rid, "a": r["a"], "b": r["b"], "left": r["left"], "owner": r["owner"],
                    "uid": r["uid"], "yields": list(route_yield(s, r))}
                    for rid, r in s.get("routes", {}).items()],
        "me": {**{key: pl[key] for key in ("gold", "techs", "research", "progress", "ready")},
               "faith": pl.get("faith", 0), "religion": pl.get("religion"),
               "score": score(s, k), "news": pl["news"], "res": resources_of(s, k),
               "can_religion": can_found_religion(s, k),
               "civics": pl.get("civics", []), "civic": pl.get("civic"),
               "cprogress": pl.get("cprogress", 0), "gov": pl.get("gov"),
               "culture": culture_turn(s, k)},
        "players": {pk: {"name": p["name"], "color": p["color"], "alive": p["alive"],
                         "ai": bool(p.get("ai")), "score": score(s, pk), "ready": p["ready"]}
                    for pk, p in s["players"].items()},
        "rel": {pk: relation(s, k, pk) for pk in s["players"] if pk != k},
        "offers": {"in": [o[0] for o in s["offers"] if o[1] == k],
                   "out": [o[1] for o in s["offers"] if o[0] == k]},
        "religions": {rid: {"name": r["name"], "belief": r["belief"], "founder": r["founder"],
                            "cities": sum(1 for c in s["cities"].values() if c.get("religion") == rid)}
                      for rid, r in s.get("religions", {}).items()},
        "rel_hold": s.get("rel_hold") or {},
        "pub": s.get("pub", []),
    }
