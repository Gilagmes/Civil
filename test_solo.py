"""Скрипт-прогон solo-режима через HTTP: проверяет весь основной поток игры."""
import json
import urllib.request

BASE = "http://127.0.0.1:8080"


def call(path, body=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(BASE + path, data=data,
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"{path} -> {e.code}: {e.read().decode()[:300]}")


def act(action, **kw):
    return call("/api/act", {"action": action, **kw})


meta = call("/api/meta")
assert "techs" in meta and "units" in meta and meta["units"]["archer"]["range"] == 2, "meta range"
print("meta ok:", len(meta["techs"]), "techs")

r = call("/api/newgame", {"name": "Тестер", "ais": 2, "difficulty": "easy"})
S = r["state"]
assert S["turn"] == 1 and len(S["players"]) == 3
mine_units = [u for u in S["units"] if u["owner"] == S["you"]]
assert len(mine_units) == 3, mine_units
settler = next(u for u in mine_units if u["type"] == "settler")
worker = next(u for u in mine_units if u["type"] == "worker")
warrior = next(u for u in mine_units if u["type"] == "warrior")
print("newgame ok, units at", settler["x"], settler["y"])

# ключи view
for key in ("roads", "cstates", "rel", "offers", "religions", "pub", "win_reason", "camps", "nwonders"):
    assert key in S, f"view lacks {key}"
print("view keys ok")

save = json.load(open("solo_save.json", encoding="utf-8"))
assert len(save.get("camps", [])) >= 2, save.get("camps")
print("camps placed:", save["camps"])

# основать город
r = act("found", unit=settler["id"])
S = r["state"]
city = next(c for c in S["cities"] if c["owner"] == S["you"])
assert city["pop"] == 1 and city["capital"]
assert "yields" in city and len(city["yields"]) == 4
print("city founded:", city["name"], "yields", city["yields"])

# исследование и постройка
r = act("research", tech="agriculture")
S = r["state"]
assert S["me"]["research"] == "agriculture"
r = act("build", city=city["id"], item="unit:warrior")
S = r["state"]
assert next(c for c in S["cities"] if c["id"] == city["id"])["build"] == "unit:warrior"
print("research+build ok")

# рабочий: ферма если на равнине, иначе просто проверка вежливого ответа
t = S["tiles"][worker["y"]][worker["x"]]
try:
    r = act("job", unit=worker["id"], job="farm" if t == "plains" else "mine")
    print("job started:", r["msg"])
except RuntimeError as e:
    print("job politely refused:", str(e)[:120])

# движение воина на соседнюю сушу
S0 = S
targets = [(warrior["x"] + dx, warrior["y"] + dy) for dx, dy in
           ((1, 0), (-1, 0), (0, 1), (0, -1))
           if 0 <= warrior["x"] + dx < S0["w"] and 0 <= warrior["y"] + dy < S0["h"]
           and S0["tiles"][warrior["y"] + dy][warrior["x"] + dx] != "water"]
r = act("move", unit=warrior["id"], x=targets[0][0], y=targets[0][1])
S = r["state"]
w2 = next(u for u in S["units"] if u["id"] == warrior["id"])
assert (w2["x"], w2["y"]) == targets[0], (w2, targets[0])
print("move ok ->", w2["x"], w2["y"])

# укрепление воина
r = act("fortify", unit=w2["id"])
print("fortify:", r["msg"][:60])

# 20 ходов: наука/стройка выбираются, конец хода, ИИ играет
for turn in range(20):
    S = call("/api/state")
    if S["winner"]:
        print("winner at turn", S["turn"], S["winner"])
        break
    me = S["me"]
    if not me["research"]:
        avail = [k for k, t in meta["techs"].items()
                 if k not in me["techs"] and all(q in me["techs"] for q in t["req"])]
        if avail:
            act("research", tech=avail[0])
    for c in S["cities"]:
        if c["owner"] == S["you"] and not c["build"]:
            try:
                act("build", city=c["id"], item="unit:warrior")
            except RuntimeError:
                pass
    # воин идёт исследовать: первый шаг в сторону от города
    r = act("end")
    S = r["state"]
print("after loop turn:", S["turn"], "gold:", S["me"]["gold"], "techs:", S["me"]["techs"])
assert S["turn"] >= 15

# города ИИ существуют
ai_cities = [c for c in S["cities"] if c["owner"] != S["you"]]
print("AI cities:", [(c["name"], c["pop"]) for c in ai_cities])
print("my cities:", [(c["name"], c["pop"], c["buildings"]) for c in S["cities"] if c["owner"] == S["you"]])
print("pub sample:", S["pub"][:3])
print("ALL OK")
