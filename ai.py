"""ИИ-игроки и автоматизация юнитов. Пользуется только публичными функциями engine."""
import logging
import random
from collections import deque
from math import comb

import engine as E

AI_NAMES = ["Цезарь", "Клеопатра", "Ганнибал", "Александр", "Тутмос", "Ашока"]
TECH_ORDER = ["agriculture", "mining", "pottery", "wheel", "bronze", "writing", "archery", "currency",
              "iron", "riding", "sailing", "math", "philosophy"]
BELIEF_ORDER = ["wisdom", "fertility", "wealth", "fervor"]
CIVIC_ORDER = ["code", "craft", "milt", "games", "polphil", "diplom"]
# характер ИИ по сложности: шанс объявить войну за ход, нужная армия, шанс принять мир, расширение
WAR_CHANCE = {"easy": 0.0, "normal": 0.07, "hard": 0.13}
ARMY_MIN = {"easy": 99, "normal": 4, "hard": 3}
PEACE_ACCEPT = {"easy": 1.0, "normal": 0.6, "hard": 0.35}
EXPAND = {"easy": -1, "normal": 0, "hard": 1}
DIRS = list(E.DIRS.items())          # [("N", (0, -1)), ...]


def is_ai(s, k):
    return bool(s["players"][k].get("ai"))


# ---------- перемещение ----------

def _owner_at(s, owners, x, y):
    cid = owners.get((x, y))
    return s["cities"][cid]["owner"] if cid else None


def _passable(s, k, x, y, military, owners):
    if not (0 <= x < E.W and 0 <= y < E.H) or s["map"][y][x] == "water" or E.cs_at(s, x, y):
        return False
    for _, v in E.units_at(s, x, y):
        if v["owner"] != k and E.relation(s, k, v["owner"]) != "war":
            return False
    c = E.city_at(s, x, y)
    if c and c[1]["owner"] != k and E.relation(s, k, c[1]["owner"]) != "war":
        return False
    o = _owner_at(s, owners, x, y)
    if military and o and o != k and E.relation(s, k, o) != "war":
        return False
    return True


def _reach(s, k, start, military, owners, maxd=30, avoid=()):
    """{клетка: (расстояние, первый шаг)} для всех достижимых клеток."""
    info = {start: (0, None)}
    q = deque([start])
    while q:
        cur = q.popleft()
        d, first = info[cur]
        if d >= maxd:
            continue
        for _, (dx, dy) in DIRS:
            n = (cur[0] + dx, cur[1] + dy)
            if n in info or n in avoid or not _passable(s, k, n[0], n[1], military, owners):
                continue
            info[n] = (d + 1, n if first is None else first)
            q.append(n)
    return info


def _step(s, k, uid, tile):
    u = s["units"].get(uid)
    if not u or u["mv"] <= 0:
        return False
    v = (tile[0] - u["x"], tile[1] - u["y"])
    for name, vec in DIRS:
        if vec == v:
            try:
                E.move_unit(s, k, uid, name)
                return True
            except E.GameError:
                return False
    return False


def _go(s, k, uid, goal, military, maxd=30):
    """Идёт к ближайшей клетке, для которой goal(x, y) истинно. True, если сдвинулся."""
    moved = False
    for _ in range(4):
        u = s["units"].get(uid)
        if not u or u["mv"] <= 0:
            break
        info = _reach(s, k, (u["x"], u["y"]), military, E.tile_owners(s), maxd)
        cands = [(d, t) for t, (d, _) in info.items() if t != (u["x"], u["y"]) and goal(*t)]
        if not cands:
            break
        _, t = min(cands)
        if not _step(s, k, uid, info[t][1]):
            break
        moved = True
    return moved


# ---------- разведчик, поселенец, рабочий ----------

def _unseen_near(s, k, x, y):
    seen = s["players"][k]["seen"]
    return any(0 <= xx < E.W and 0 <= yy < E.H and not seen[yy * E.W + xx]
               for yy in range(y - 2, y + 3) for xx in range(x - 2, x + 3))


def do_scout(s, k, uid):
    """Исследует карту. False — исследовать больше нечего."""
    u = s["units"][uid]
    if u["mv"] <= 0:
        return True
    return _go(s, k, uid, lambda x, y: _unseen_near(s, k, x, y), False)


def _site_ok(s, k, x, y, owners):
    if s["map"][y][x] == "water":
        return False
    for c in list(s["cities"].values()) + list(s.get("cstates", {}).values()):
        if E.dist((x, y), (c["x"], c["y"])) < 3:
            return False
    o = _owner_at(s, owners, x, y)
    return not o or o == k


def _site_score(s, x, y):
    sc = 0.0
    for yy in range(max(0, y - 2), min(E.H, y + 3)):
        for xx in range(max(0, x - 2), min(E.W, x + 3)):
            f, p = E.tile_yield(s, xx, yy)
            sc += f * 1.5 + p
    return sc


def _join_nearest(s, k, uid):
    """Бесполезный поселенец идёт в ближайший свой город и вливается в него."""
    u = s["units"].get(uid)
    mine = [c for c in s["cities"].values() if c["owner"] == k]
    if not u or not mine:
        return False
    c = min(mine, key=lambda c: E.dist((c["x"], c["y"]), (u["x"], u["y"])))
    if (c["x"], c["y"]) == (u["x"], u["y"]):
        try:
            E.join_city(s, k, uid)
            return True
        except E.GameError:
            return False
    _go(s, k, uid, lambda x, y: (x, y) == (c["x"], c["y"]), False)
    u = s["units"].get(uid)
    if u and (u["x"], u["y"]) == (c["x"], c["y"]):
        try:
            E.join_city(s, k, uid)
        except E.GameError:
            pass
    return True


def do_settler(s, k, uid):
    blocked = set()                                  # первые шаги, в которые не пройти (чужие юниты и т.п.)
    for _ in range(8):
        u = s["units"].get(uid)
        if not u or u["mv"] <= 0:
            return
        pos = (u["x"], u["y"])
        owners = E.tile_owners(s)
        info = _reach(s, k, pos, False, owners, 9, blocked)
        best = None
        for t, (d, first) in info.items():
            if _site_ok(s, k, t[0], t[1], owners):
                sc = _site_score(s, *t) - 2.5 * d
                if "sailing" in s["players"][k]["techs"] and _water_nb(s, *t):
                    sc += 3                           # порт для галер
                if best is None or sc > best[0]:
                    best = (sc, t, first)
        if best is None:
            if "sailing" in s["players"][k]["techs"] and _overseas_sites(s, k, owners):
                return                               # ждёт галеру на берегу
            if _join_nearest(s, k, uid):             # мест нет — вливается в город
                return
            name, _ = random.choice(DIRS)
            try:
                E.move_unit(s, k, uid, name)
            except E.GameError:
                pass
            return
        _, t, first = best
        if t == pos:
            try:
                E.found_city(s, k, uid)
            except E.GameError:
                pass
            return
        if not _step(s, k, uid, first):
            blocked.add(first)                       # пробуем обойти другим путём


# ---------- флот: перевозка поселенцев на другие острова ----------

def _water_reach(s, k, start, maxd=24):
    """{водная клетка: (расстояние, первый шаг)} для галеры из клетки start."""
    info = {start: (0, None)}
    q = deque([start])
    while q:
        cur = q.popleft()
        d, first = info[cur]
        if d >= maxd:
            continue
        for _, (dx, dy) in DIRS:
            n = (cur[0] + dx, cur[1] + dy)
            if n in info or not (0 <= n[0] < E.W and 0 <= n[1] < E.H) or s["map"][n[1]][n[0]] != "water":
                continue
            if any(v["owner"] != k for _, v in E.units_at(s, *n)):
                continue
            info[n] = (d + 1, n if first is None else first)
            q.append(n)
    return info


def _water_nb(s, x, y):
    return [(x + dx, y + dy) for _, (dx, dy) in DIRS
            if 0 <= x + dx < E.W and 0 <= y + dy < E.H and s["map"][y + dy][x + dx] == "water"]


def _overseas_sites(s, k, owners):
    """Места под города, до которых нельзя дойти по суше от города игрока: {клетка: [соседние водные]}."""
    mine = [c for c in s["cities"].values() if c["owner"] == k]
    if not mine:
        return {}
    cap = next((c for c in mine if c["capital"]), mine[0])
    land = _reach(s, k, (cap["x"], cap["y"]), False, owners, 60)
    out = {}
    for y in range(E.H):
        for x in range(E.W):
            if (x, y) not in land and _site_ok(s, k, x, y, owners):
                ws = _water_nb(s, x, y)
                if ws:
                    out[(x, y)] = ws
    return out


def _stranded(s, k, uid, owners):
    """Поселенец, которому по суше некуда идти."""
    u = s["units"][uid]
    if u.get("aboard") or u["type"] != "settler":
        return False
    info = _reach(s, k, (u["x"], u["y"]), False, owners, 9)
    return not any(_site_ok(s, k, t[0], t[1], owners) for t in info)


def _ferry_needed(s, k):
    """Нужна ли галера: есть острова для заселения, а по суше места кончились."""
    if "sailing" not in s["players"][k]["techs"]:
        return False
    owners = E.tile_owners(s)
    if not _overseas_sites(s, k, owners):
        return False
    mine = [c for c in s["cities"].values() if c["owner"] == k]
    if not mine:
        return False
    cap = next((c for c in mine if c["capital"]), mine[0])
    land = _reach(s, k, (cap["x"], cap["y"]), False, owners, 60)
    no_land_sites = not any(_site_ok(s, k, t[0], t[1], owners) for t in land)
    return no_land_sites or any(_stranded(s, k, i, owners) for i, u in s["units"].items()
                                if u["owner"] == k and u["type"] == "settler")


def _sail(s, k, bid, goal):
    """Галера плывёт к ближайшей водной клетке с goal(x, y). True, если сдвинулась."""
    moved = False
    for _ in range(4):
        b = s["units"].get(bid)
        if not b or b["mv"] <= 0:
            break
        info = _water_reach(s, k, (b["x"], b["y"]))
        cands = [(d, t) for t, (d, _) in info.items() if t != (b["x"], b["y"]) and goal(*t)]
        if not cands:
            break
        _, t = min(cands)
        first = info[t][1]
        name = next(n for n, v in DIRS if v == (first[0] - b["x"], first[1] - b["y"]))
        try:
            E.move_unit(s, k, bid, name)
        except E.GameError:
            break
        moved = True
    return moved


def _dir_to(frm, to):
    return next((n for n, v in DIRS if v == (to[0] - frm[0], to[1] - frm[1])), None)


def _run_galley(s, k, bid, owners):
    over = _overseas_sites(s, k, owners)
    if not over:
        return
    cargo = [i for i, v in s["units"].items() if v.get("aboard") == bid and v["type"] == "settler"]
    if not cargo:                                    # 1. забрать застрявшего поселенца с берега
        strand = [(i, u) for i, u in s["units"].items()
                  if u["owner"] == k and _stranded(s, k, i, owners) and _water_nb(s, u["x"], u["y"])]
        if not strand:
            return
        b = s["units"][bid]
        sid, su = min(strand, key=lambda t: E.dist((b["x"], b["y"]), (t[1]["x"], t[1]["y"])))
        near = set(_water_nb(s, su["x"], su["y"]))
        if (b["x"], b["y"]) not in near:
            _sail(s, k, bid, lambda x, y: (x, y) in near)
        b = s["units"].get(bid)
        if not b or (b["x"], b["y"]) not in near:
            return
        try:
            E.move_unit(s, k, sid, _dir_to((su["x"], su["y"]), (b["x"], b["y"])))   # посадка
        except E.GameError:
            return
        cargo = [sid]
    # 2. отвезти на лучшее место на другом острове
    b = s["units"][bid]
    info = _water_reach(s, k, (b["x"], b["y"]))
    best = None
    for site, ws in over.items():
        for w in ws:
            if w in info:
                sc = _site_score(s, *site) - 2 * info[w][0]
                if best is None or sc > best[0]:
                    best = (sc, site, w)
    if not best:
        return
    _, site, w = best
    if (b["x"], b["y"]) != w:
        _sail(s, k, bid, lambda x, y: (x, y) == w)
    b = s["units"].get(bid)
    if b and (b["x"], b["y"]) == w and s["units"][cargo[0]]["mv"] > 0:
        try:
            E.move_unit(s, k, cargo[0], _dir_to(w, site))   # высадка
        except E.GameError:
            pass


def do_navy(s, k):
    boats = [i for i, u in s["units"].items() if u["owner"] == k and E.UNITS[u["type"]].get("naval")]
    for bid in boats:
        if bid in s["units"]:
            _run_galley(s, k, bid, E.tile_owners(s))


def _job_here(s, k, x, y):
    techs = s["players"][k]["techs"]
    terr = s["map"][y][x]
    if E.city_at(s, x, y) or f"{x},{y}" in s["impr"]:
        return None
    for job, im in E.IMPR.items():
        if im["on"] == terr and im["req"] in techs:
            return job
    return None


def _path(s, k, start, goal, owners):
    """Кратчайший путь по суше (без чужой земли) от start до goal; пустой список, если пути нет."""
    prev = {start: None}
    q = deque([start])
    while q:
        cur = q.popleft()
        if cur == goal:
            break
        for _, (dx, dy) in DIRS:
            n = (cur[0] + dx, cur[1] + dy)
            if n in prev or not (0 <= n[0] < E.W and 0 <= n[1] < E.H):
                continue
            if s["map"][n[1]][n[0]] == "water" or E.cs_at(s, *n):
                continue
            o = _owner_at(s, owners, *n)
            if o and o != k:
                continue
            prev[n] = cur
            q.append(n)
    if goal not in prev:
        return []
    path, cur = [], goal
    while cur:
        path.append(cur)
        cur = prev[cur]
    return path


def _road_targets(s, k, owners):
    """Клетки без дороги на пути от первого несвязанного города к столице."""
    cities = [c for c in s["cities"].values() if c["owner"] == k]
    cap = next((c for c in cities if c["capital"]), None)
    if not cap:
        return set()
    busy = {(u["x"], u["y"]) for u in s["units"].values() if u["job"] == "road"}
    for c in cities:
        if c is cap or E.road_connected(s, c):
            continue
        out = {t for t in _path(s, k, (c["x"], c["y"]), (cap["x"], cap["y"]), owners)
               if not E.has_road(s, *t)} - busy
        if out:
            return out
    return set()


def do_worker(s, k, uid):
    u = s["units"][uid]
    if u["job"] or u["mv"] <= 0:
        return
    mine = [c for c in s["cities"].values() if c["owner"] == k]
    if not mine:
        return

    def worth(x, y):
        if not _job_here(s, k, x, y):
            return False
        o = _owner_at(s, owners, x, y)
        return o == k or (o is None and any(E.dist((x, y), (c["x"], c["y"])) <= 2 for c in mine))

    def road_step():
        """Дорога: 'done' — работа начата, 'moved' — идём к цели, None — дорог строить не нужно."""
        if "wheel" not in s["players"][k]["techs"]:
            return None
        targets = _road_targets(s, k, owners)
        u = s["units"].get(uid)
        if u and (u["x"], u["y"]) in targets:
            try:
                E.start_job(s, k, uid, "road")
                return "done"
            except E.GameError:
                return None
        if targets and _go(s, k, uid, lambda x, y: (x, y) in targets, False, 14):
            return "moved"
        return None

    # каждый третий рабочий сначала строит дороги к столице (+золото), остальные — сначала улучшения
    roads_first = int(uid) % 3 == 0
    for _ in range(3):
        u = s["units"].get(uid)
        if not u or u["mv"] <= 0:
            return
        owners = E.tile_owners(s)
        if roads_first:
            r = road_step()
            if r == "done":
                return
            if r == "moved":
                continue
        if worth(u["x"], u["y"]):
            try:
                E.start_job(s, k, uid, _job_here(s, k, u["x"], u["y"]))
            except E.GameError:
                pass
            return
        if _go(s, k, uid, worth, False, 10):
            continue
        if not roads_first:
            r = road_step()
            if r == "done":
                return
            if r == "moved":
                continue
        return


def auto_step(s, k, uid):
    """Один шаг автоматического юнита. False — автоматизировать больше нечего."""
    u = s["units"].get(uid)
    if not u:
        return False
    if u["type"] == "scout":
        return do_scout(s, k, uid)
    if u["type"] == "worker":
        do_worker(s, k, uid)
        return True
    return False


# ---------- армия ----------

def _mil(s, k):
    return [(i, u) for i, u in s["units"].items()
            if u["owner"] == k and E.UNITS[u["type"]]["att"] > 0 and not E.UNITS[u["type"]].get("naval")]


def _fortify(s, k, uid):
    try:
        E.fortify(s, k, uid)
    except E.GameError:
        pass


def _preach_cities(s, k):
    """Города, которые миссионер ИИ может обратить (чужая вера или без веры, не священные)."""
    rid = s["players"][k].get("religion")
    rels = s.get("religions", {})
    return [(cid, c) for cid, c in s["cities"].items()
            if rid and c.get("religion") != rid
            and not (c.get("religion") and rels.get(c["religion"], {}).get("holy") == cid)]


def do_missionary(s, k, uid):
    targets = _preach_cities(s, k)
    u = s["units"].get(uid)
    if not u or not targets:
        return
    for _ in range(3):
        u = s["units"].get(uid)
        if not u:
            return
        near = E.preach_targets(s, k, uid)
        if near:
            try:
                E.preach(s, k, uid, near[0][0])
            except E.GameError:
                pass
            return
        if u["mv"] <= 0:
            return
        tiles = {(c["x"], c["y"]) for _, c in targets}
        if not _go(s, k, uid, lambda x, y: any(E.dist((x, y), t) <= 1 for t in tiles), False, 16):
            return


def do_trader(s, k, uid):
    """Караван: идёт в ближайший свой город и открывает путь в самый дальний."""
    u = s["units"].get(uid)
    if not u or u["owner"] != k or u["type"] != "trader" or u["job"]:
        return
    mine = {cid: c for cid, c in s["cities"].items() if c["owner"] == k}
    if len(mine) < 2:
        return
    origin = E.city_at(s, u["x"], u["y"])
    if not origin or origin[1]["owner"] != k:
        home = min(mine.values(), key=lambda c: E.dist((u["x"], u["y"]), (c["x"], c["y"])))
        _go(s, k, uid, (home["x"], home["y"]), False)
        return
    dest = max(((cid, c) for cid, c in mine.items() if cid != origin[0]),
               key=lambda t: E.dist((origin[1]["x"], origin[1]["y"]), (t[1]["x"], t[1]["y"])))
    try:
        E.start_route(s, k, uid, dest[0])
    except E.GameError:
        pass


def _win_prob(a, d, ahp, dhp):
    """Вероятность победы атакующего (сила a против защиты d, здоровье ahp и dhp): раунды по 3 урона."""
    p = a / (a + d)
    need_a, need_d = -(-dhp // 3), -(-ahp // 3)
    return sum(comb(need_a - 1 + j, j) * p ** need_a * (1 - p) ** j for j in range(need_d))


def _odds(s, k, u, x, y):
    """Шансы юнита u атаковать клетку (x, y): (вероятность победы, цель) или None, если там нет врага."""
    if not (0 <= x < E.W and 0 <= y < E.H) or s["map"][y][x] == "water" or E.cs_at(s, x, y):
        return None
    others = [v for _, v in E.units_at(s, x, y) if v["owner"] != k and E.relation(s, k, v["owner"]) == "war"]
    town = E.city_at(s, x, y)
    if town and (town[1]["owner"] == k or E.relation(s, k, town[1]["owner"]) != "war"):
        town = None
    if not others and not town:
        return None
    mil = [v for v in others if E.UNITS[v["type"]]["def"] > 0]
    if not mil:
        return 1.0, "empty"
    d = max(mil, key=lambda v: E.UNITS[v["type"]]["def"] * v["hp"])
    dstr = E._defense(s, d, x, y, town, u["type"])
    return _win_prob(E.UNITS[u["type"]]["att"], dstr, u["hp"], d["hp"]), "fight"


def _strike(s, k, uid, min_prob):
    """Атакует выгодную соседнюю цель. True, если атака состоялась."""
    u = s["units"].get(uid)
    if not u or u["mv"] <= 0 or E.UNITS[u["type"]]["att"] <= 0:
        return False
    best = None
    for name, (dx, dy) in DIRS:
        o = _odds(s, k, u, u["x"] + dx, u["y"] + dy)
        if o and (best is None or o[0] > best[0]):
            best = (o[0], name)
    if best and best[0] >= min_prob:
        try:
            E.move_unit(s, k, uid, best[1])
            return True
        except E.GameError:
            return False
    return False


def _ranged_strike(s, k, uid):
    """ИИ-стрелок: бьёт самого раненого врага в радиусе (без риска для себя)."""
    u = s["units"].get(uid)
    if not u or u["mv"] <= 0 or not E.UNITS[u["type"]].get("range"):
        return False
    rng = E.UNITS[u["type"]]["range"]
    targets = [v for v in s["units"].values()
               if v["owner"] != k and (v["owner"] == "barb" or E.relation(s, k, v["owner"]) == "war")
               and 1 <= E.dist((u["x"], u["y"]), (v["x"], v["y"])) <= rng]
    if not targets:
        return False
    t = min(targets, key=lambda v: v["hp"])
    try:
        E.ranged_attack(s, k, uid, t["x"], t["y"])
        return True
    except E.GameError:
        return False


def _ai_upgrades(s, k):
    """ИИ улучшает ветеранов, когда есть избыток золота."""
    p = s["players"][k]
    for uid, u in list(s["units"].items()):
        if u["owner"] != k or u["type"] not in E.UPGRADES:
            continue
        to = E.UPGRADES[u["type"]]
        t = E.UNITS[to]
        if t["req"] and t["req"] not in p["techs"]:
            continue
        if E.UNIT_RES.get(to) and E.resources_of(s, k)[E.UNIT_RES[to]] <= 0:
            continue
        if p["gold"] < E.upgrade_price(u["type"], to) + 40:
            continue
        try:
            E.upgrade_unit(s, k, uid)
        except E.GameError:
            pass


def _home_tiles(s, k):
    return {(c["x"], c["y"]) for c in s["cities"].values() if c["owner"] == k}


def _retreat(s, k, uid):
    home = _home_tiles(s, k)
    u = s["units"].get(uid)
    if not u or not home:
        return
    if (u["x"], u["y"]) not in home:
        _go(s, k, uid, lambda x, y: (x, y) in home, True)
        u = s["units"].get(uid)
    if u and (u["x"], u["y"]) in home and not u["fort"]:
        _fortify(s, k, uid)


def _enemy_military(s, k):
    return [(u["x"], u["y"]) for u in s["units"].values()
            if u["owner"] != k and E.UNITS[u["type"]]["att"] > 0
            and (u["owner"] == "barb" or E.relation(s, k, u["owner"]) == "war")]


def military_v2(s, k):
    """Боевой ИИ: гарнизоны, ответные удары, отступление раненых, осада с накоплением сил."""
    mine = _mil(s, k)
    cities = [(cid, c) for cid, c in s["cities"].items() if c["owner"] == k]
    garrison = {}
    for cid, c in cities:
        here = [(i, u) for i, u in mine if (u["x"], u["y"]) == (c["x"], c["y"])]
        if here:
            garrison[cid] = max(here, key=lambda t: (E.UNITS[t[1]["type"]]["def"], t[1]["hp"]))[0]
    guarded = set(garrison.values())
    for uid in guarded:
        if not s["units"][uid]["fort"]:
            _fortify(s, k, uid)
    free = [i for i, _ in mine if i not in guarded]
    # 1. закрыть пустые города
    for cid, c in cities:
        if cid in garrison or not free:
            continue
        tgt = (c["x"], c["y"])
        best = min(free, key=lambda i: E.dist((s["units"][i]["x"], s["units"][i]["y"]), tgt))
        free.remove(best)
        _go(s, k, best, lambda x, y, tgt=tgt: (x, y) == tgt, True)
        u = s["units"].get(best)
        if u and (u["x"], u["y"]) == tgt:
            _fortify(s, k, best)
    # 2. раненые отступают лечиться
    rest = []
    for uid in free:
        u = s["units"].get(uid)
        if not u:
            continue
        if u["hp"] <= 4:
            _retreat(s, k, uid)
        else:
            rest.append(uid)
    # 3. ответные удары по врагу рядом (только с хорошими шансами)
    for uid in list(rest):
        if _strike(s, k, uid, 0.6):
            rest.remove(uid)
    # 4. угроза городам: враг в трёх клетках — держимся рядом и бьём, когда выгодно
    enemies = _enemy_military(s, k)
    home = _home_tiles(s, k)
    if enemies and any(E.dist(e, h) <= 3 for e in enemies for h in home):
        for uid in rest:
            u = s["units"].get(uid)
            if u and not _strike(s, k, uid, 0.55):
                _retreat(s, k, uid)
        return
    # 5. охота на варваров неподалёку
    barbs = {(u["x"], u["y"]) for u in s["units"].values() if u["owner"] == "barb"}
    campaign = []
    for uid in rest:
        u = s["units"].get(uid)
        if not u:
            continue
        if barbs and E.UNITS[u["type"]]["att"] >= 3 and u["hp"] >= 7:
            info = _reach(s, k, (u["x"], u["y"]), True, E.tile_owners(s), 4)
            if any(t in info for t in barbs):
                _go(s, k, uid, lambda x, y: (x, y) in barbs, True, 4)
                _strike(s, k, uid, 0.55)
                continue
        campaign.append(uid)
    # 6. война: копим силы, затем идём на город
    targets = [(c["x"], c["y"], c) for c in s["cities"].values()
               if c["owner"] != k and E.relation(s, k, c["owner"]) == "war"]
    if targets and campaign and home:
        tx, ty, tc = min(targets, key=lambda t: min(E.dist((t[0], t[1]), h) for h in home))
        defenders = [v for _, v in E.units_at(s, tx, ty) if E.UNITS[v["type"]]["def"] > 0]
        siege = sum(1 for uid in campaign if s["units"][uid]["type"] == "catapult")
        need = max(3, len(defenders) + 2) + (1 if "walls" in tc["buildings"] and not siege else 0)
        fit = [uid for uid in campaign if s["units"][uid]["hp"] >= 7]
        if len(fit) >= need:                                  # сил достаточно — штурм
            for uid in fit:
                if uid in s["units"]:
                    _go(s, k, uid, lambda x, y: (x, y) == (tx, ty), True)
            for uid in campaign:
                if uid not in fit:
                    _retreat(s, k, uid)
            return
        stage = min(home, key=lambda h: E.dist(h, (tx, ty)))   # иначе собираемся у ближайшего своего города
        for uid in campaign:
            u = s["units"].get(uid)
            if not u:
                continue
            if (u["x"], u["y"]) != stage:
                _go(s, k, uid, lambda x, y: (x, y) == stage, True)
                u = s["units"].get(uid)
            if u and (u["x"], u["y"]) == stage and not u["fort"]:
                _fortify(s, k, uid)
        return
    for uid in campaign:
        _retreat(s, k, uid)


def do_military(s, k):
    _ai_upgrades(s, k)
    for uid in [i for i, u in s["units"].items()
                if u["owner"] == k and E.UNITS[u["type"]].get("range")]:
        _ranged_strike(s, k, uid)
    if s["players"][k].get("ai_v1"):          # старое поведение (для сравнения в тестах)
        return _military_v1(s, k)
    return military_v2(s, k)


def _military_v1(s, k):
    mine = _mil(s, k)
    cities = [(cid, c) for cid, c in s["cities"].items() if c["owner"] == k]
    garrison = {}
    for cid, c in cities:
        here = [(i, u) for i, u in mine if (u["x"], u["y"]) == (c["x"], c["y"])]
        if here:
            garrison[cid] = max(here, key=lambda t: (E.UNITS[t[1]["type"]]["def"], t[1]["hp"]))[0]
    guarded = set(garrison.values())
    for uid in guarded:
        if not s["units"][uid]["fort"]:
            _fortify(s, k, uid)
    free = [i for i, _ in mine if i not in guarded]
    # 1. закрыть пустые города ближайшими свободными юнитами
    for cid, c in cities:
        if cid in garrison or not free:
            continue
        tgt = (c["x"], c["y"])
        best = min(free, key=lambda i: E.dist((s["units"][i]["x"], s["units"][i]["y"]), tgt))
        free.remove(best)
        _go(s, k, best, lambda x, y, tgt=tgt: (x, y) == tgt, True)
        u = s["units"].get(best)
        if u and (u["x"], u["y"]) == tgt:
            _fortify(s, k, best)
    # 2. охота на варваров рядом
    barbs = {(u["x"], u["y"]) for u in s["units"].values() if u["owner"] == "barb"}
    rest = []
    for uid in free:
        u = s["units"].get(uid)
        if not u:
            continue
        if barbs and E.UNITS[u["type"]]["att"] >= 3 and u["hp"] >= 6:
            info = _reach(s, k, (u["x"], u["y"]), True, E.tile_owners(s), 4)
            if any(t in info for t in barbs):
                _go(s, k, uid, lambda x, y: (x, y) in barbs, True, 4)
                continue
        rest.append(uid)
    # 3. войны: армия идёт на ближайший вражеский город
    targets = {(c["x"], c["y"]) for c in s["cities"].values()
               if c["owner"] != k and E.relation(s, k, c["owner"]) == "war"}
    if targets and len(rest) >= 3:
        for uid in rest:
            if uid in s["units"]:
                _go(s, k, uid, lambda x, y: (x, y) in targets, True)
        return
    # 4. иначе стоять в городах
    home = {(c["x"], c["y"]) for _, c in cities}
    for uid in rest:
        u = s["units"].get(uid)
        if not u:
            continue
        if (u["x"], u["y"]) not in home and home:
            _go(s, k, uid, lambda x, y: (x, y) in home, True)
            u = s["units"].get(uid)
        if u and (u["x"], u["y"]) in home and not u["fort"]:
            _fortify(s, k, uid)


# ---------- дипломатия ----------

def _diplomacy(s, k, events):
    me = len(_mil(s, k))
    for frm, to in list(s["offers"]):
        if to == k and E.relation(s, k, frm) == "war" and random.random() < PEACE_ACCEPT[E.difficulty(s)]:
            try:
                events.append(E.accept_peace(s, k, frm)[1])
            except E.GameError:
                pass
    for o, q in s["players"].items():
        if o != k and q["alive"] and E.relation(s, k, o) == "war" and me < 2 and [k, o] not in s["offers"]:
            try:
                E.propose_peace(s, k, o)
            except E.GameError:
                pass
    at_war = any(E.relation(s, k, o) == "war" and q["alive"] for o, q in s["players"].items() if o != k)
    if (s["turn"] >= 12 and me >= ARMY_MIN[E.difficulty(s)] and not at_war
            and random.random() < WAR_CHANCE[E.difficulty(s)]):
        my_cities = [c for c in s["cities"].values() if c["owner"] == k]
        cands = []
        for o, q in s["players"].items():
            if o == k or not q["alive"] or E.score(s, o) > E.score(s, k) * 1.3:
                continue
            theirs = [c for c in s["cities"].values() if c["owner"] == o]
            if my_cities and theirs:
                d = min(E.dist((a["x"], a["y"]), (b["x"], b["y"])) for a in my_cities for b in theirs)
                cands.append((d, o))
        if cands:
            try:
                events.append(E.declare_war(s, k, min(cands)[1])[1])
            except E.GameError:
                pass


# ---------- города ----------

def _best_military(items):
    best, key = None, -1
    for item, (_, _, _) in items.items():
        if item.startswith("unit:"):
            u = E.UNITS[item[5:]]
            if u["att"] > 0 and item != "unit:catapult" and not u.get("naval") and u["def"] * 2 + u["att"] > key:
                best, key = item, u["def"] * 2 + u["att"]
    return best


def _choose(s, k, c, ctx):
    items = {i[0]: i for i in E.available_items(s, k, c)}
    pos = (c["x"], c["y"])
    guarded = any((u["x"], u["y"]) == pos for _, u in ctx["mil"])
    best_mil = _best_military(items)
    prod = ctx["prod"]
    if not guarded and best_mil and not prod.get("mil"):
        return best_mil, "mil"
    if ("unit:missionary" in items and s["turn"] >= 12 and ctx["missionaries"] + prod.get("missionary", 0) < 1
            and ctx["preach"] > 0 and E.city_yields(s, c)[1] >= 3):
        return "unit:missionary", "missionary"
    if ctx["ferry"] and "unit:galley" in items and ctx["galleys"] + prod.get("galley", 0) == 0:
        return "unit:galley", "galley"
    if (ctx["war"] and "unit:catapult" in items and ctx["catapults"] + prod.get("catapult", 0) < 2
            and len(ctx["mil"]) >= 3):
        return "unit:catapult", "catapult"
    want = min(7, 3 + s["turn"] // 8 + EXPAND[E.difficulty(s)])
    ferry_ready = ctx["galleys"] + prod.get("galley", 0) > 0
    if ("unit:settler" in items and ctx["sites"] > 0 and (ctx["land_sites"] > 0 or ferry_ready)
            and s["turn"] < 50 and ctx["settlers"] + prod.get("settler", 0) < ctx["sites"]
            and ctx["cities"] + ctx["settlers"] + prod.get("settler", 0) < want):
        return "unit:settler", "settler"
    if "unit:worker" in items and ctx["workers"] + prod.get("worker", 0) < ctx["cities"]:
        return "unit:worker", "worker"
    if ("unit:trader" in items and ctx["cities"] >= 2
            and ctx["traders"] + prod.get("trader", 0) < min(4, ctx["cities"] - 1)):
        return "unit:trader", "trader"
    if "unit:scout" in items and s["turn"] < 25 and ctx["scouts"] + prod.get("scout", 0) == 0:
        return "unit:scout", "scout"
    order = (["granary"] if c["pop"] >= 2 else []) + ["library", "temple", "market", "workshop"]
    if ctx["threat"]:
        order.insert(0, "walls")
    for key in order:
        if f"bld:{key}" in items:
            return f"bld:{key}", None
    if E.city_yields(s, c)[1] >= 5:
        w = [i for i in items if i.startswith("wnd:") and i not in ctx["wonders"]]
        if w:
            pick = min(w, key=lambda i: items[i][2])
            ctx["wonders"].add(pick)
            return pick, None
    if best_mil and len(ctx["mil"]) + prod.get("mil", 0) < 2 * ctx["cities"] + 2:
        return best_mil, "mil"
    if "unit:worker" in items and ctx["workers"] + prod.get("worker", 0) < 2 * ctx["cities"]:
        return "unit:worker", "worker"
    return (best_mil, "mil") if best_mil else (None, None)


def _cities(s, k):
    p = s["players"][k]
    units = list(s["units"].values())
    mine = {cid: c for cid, c in s["cities"].items() if c["owner"] == k}
    owners = E.tile_owners(s)
    sites = land_sites = 0
    cap = next((c for c in mine.values() if c["capital"]), next(iter(mine.values()), None))
    land = _reach(s, k, (cap["x"], cap["y"]), False, owners, 60) if cap else {}
    for y in range(E.H):
        for x in range(E.W):
            if _site_ok(s, k, x, y, owners) and any(E.dist((x, y), (c["x"], c["y"])) <= 8 for c in mine.values()):
                sites += 1
                land_sites += (x, y) in land
    ctx = {"cities": len(mine), "mil": _mil(s, k), "sites": sites, "land_sites": land_sites, "wonders": set(),
           "workers": sum(1 for u in units if u["owner"] == k and u["type"] == "worker"),
           "traders": sum(1 for u in units if u["owner"] == k and u["type"] == "trader"),
           "scouts": sum(1 for u in units if u["owner"] == k and u["type"] == "scout"),
           "settlers": sum(1 for u in units if u["owner"] == k and u["type"] == "settler"),
           "missionaries": sum(1 for u in units if u["owner"] == k and u["type"] == "missionary"),
           "galleys": sum(1 for u in units if u["owner"] == k and u["type"] == "galley"),
           "catapults": sum(1 for u in units if u["owner"] == k and u["type"] == "catapult"),
           "war": any(E.relation(s, k, o) == "war" and q["alive"] and any(c["owner"] == o for c in s["cities"].values())
                      for o, q in s["players"].items() if o != k),
           "ferry": _ferry_needed(s, k),
           "preach": len(_preach_cities(s, k)),
           "threat": any(u["owner"] == "barb" for u in units)
                     or any(E.relation(s, k, o) == "war" for o, q in s["players"].items() if o != k and q["alive"]),
           "prod": {}}
    for c in mine.values():                         # что уже строится
        if c["build"]:
            kind = c["build"].split(":")[1] if c["build"].startswith("unit:") else None
            tag = {"settler": "settler", "worker": "worker", "scout": "scout",
                   "missionary": "missionary", "galley": "galley", "trader": "trader",
                   "catapult": "catapult"}.get(kind, "mil" if kind else None)
            if tag:
                ctx["prod"][tag] = ctx["prod"].get(tag, 0) + 1
            if c["build"].startswith("wnd:"):
                ctx["wonders"].add(c["build"])
    for cid, c in mine.items():
        if not c["build"]:
            item, tag = _choose(s, k, c, ctx)
            if item:
                try:
                    E.set_build(s, k, cid, item)
                except E.GameError:
                    continue
                if tag:
                    ctx["prod"][tag] = ctx["prod"].get(tag, 0) + 1
        price = E.buy_price(s, c)
        if c["build"] and price and not c["build"].startswith("wnd:") and price <= 45 and p["gold"] - price >= 12:
            try:
                E.buy(s, k, cid)
            except E.GameError:
                pass


def _city_states(s, k):
    p = s["players"][k]
    for csid, cs in s.get("cstates", {}).items():
        if (p["seen"][cs["y"] * E.W + cs["x"]] and k not in cs["war"]
                and p["gold"] >= E.CS_GIFT + 40 and random.random() < 0.3):
            try:
                E.cs_gift(s, k, csid)
            except E.GameError:
                pass


# ---------- вход ----------

def play_turn(s, k):
    """Полный ход ИИ-игрока. Возвращает публичные события (объявления войны/мира)."""
    events = []
    p = s["players"][k]
    try:
        if not p["research"]:
            av = E.available_techs(s, k)
            if av:
                E.set_research(s, k, min(av, key=lambda t: TECH_ORDER.index(t) if t in TECH_ORDER else 99))
        if not p.get("civic"):                                   # институты за культуру
            av = E.available_civics(s, k)
            if av:
                E.set_civic(s, k, min(av, key=lambda t: CIVIC_ORDER.index(t) if t in CIVIC_ORDER else 99))
        if not p.get("gov") and E.has_civic(s, k, "polphil"):    # строй: война — автократия, иначе республика
            at_war = any(E.relation(s, k, o) == "war" and q["alive"]
                         for o, q in s["players"].items() if o != k)
            E.set_gov(s, k, "autocracy" if at_war else "republic")
        _diplomacy(s, k, events)
        if E.can_found_religion(s, k):
            try:
                events.append(E.found_religion(s, k, random.choice(BELIEF_ORDER))[1])
            except E.GameError:
                pass
        do_navy(s, k)
        for uid in [i for i, u in s["units"].items() if u["owner"] == k and u["type"] == "settler"]:
            if uid in s["units"]:
                do_settler(s, k, uid)
        for uid in [i for i, u in s["units"].items() if u["owner"] == k and u["type"] in ("worker", "scout")]:
            if uid in s["units"]:
                auto_step(s, k, uid)
        for uid in [i for i, u in s["units"].items() if u["owner"] == k and u["type"] == "missionary"]:
            if uid in s["units"]:
                do_missionary(s, k, uid)
        for uid in [i for i, u in s["units"].items() if u["owner"] == k and u["type"] == "trader"]:
            if uid in s["units"]:
                do_trader(s, k, uid)
        do_military(s, k)
        _cities(s, k)
        _city_states(s, k)
    except Exception:
        logging.exception("Ошибка ИИ-игрока %s", p["name"])
    E.set_ready(s, k)
    return events


def play_all(s):
    """Ходы всех ИИ и автоматических юнитов людей. Вызывать в начале хода."""
    events = []
    for k, p in list(s["players"].items()):
        if not p["alive"]:
            continue
        if p.get("ai"):
            events += play_turn(s, k)
        else:
            for uid in [i for i, u in s["units"].items() if u["owner"] == k and u.get("auto")]:
                try:
                    if not auto_step(s, k, uid):
                        s["units"][uid]["auto"] = False
                        E._news(s, k, "🧭 Юнит закончил разведку и перешёл на ручное управление")
                except Exception:
                    logging.exception("Ошибка автоюнита")
    return events
