"""HTTP API и страница Mini App. Работает в одном процессе с ботом.

setup(..., solo=True) включает одиночный режим для браузера без Telegram:
авторизация не нужна, игрок один («me»), соперники — ИИ.
"""
import hashlib
import hmac
import json
import os
import time
from urllib.parse import parse_qsl

from aiohttp import web

import engine as E
import hints as H

WEB_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "web")


def check_init_data(init_data, token, max_age=86400):
    """Проверяет подпись данных Telegram Mini App. Возвращает dict или None."""
    data = dict(parse_qsl(init_data, keep_blank_values=True))
    got = data.pop("hash", "")
    check = "\n".join(f"{k}={v}" for k, v in sorted(data.items()))
    secret = hmac.new(b"WebAppData", token.encode(), hashlib.sha256).digest()
    calc = hmac.new(secret, check.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(calc, got):
        return None
    try:
        if time.time() - int(data.get("auth_date", 0)) > max_age:
            return None
    except ValueError:
        return None
    return data


def _fail(cls, text):
    return cls(text=json.dumps({"error": text}, ensure_ascii=False),
               content_type="application/json")


def _meta():
    """Статические справочники для клиента (не секрет)."""
    return {
        "terrain": {k: {x: v[x] for x in ("name", "emoji", "f", "p", "cost", "def")}
                    for k, v in E.TERRAIN.items()},
        "units": {k: {"name": v["name"], "att": v["att"], "def": v["def"], "moves": v["moves"],
                      "vision": v["vision"], "range": v.get("range", 0), "naval": bool(v.get("naval")),
                      "cap": v.get("cap", 0), "cost": v["cost"], "req": v["req"]}
                  for k, v in E.UNITS.items()},
        "impr": {k: {x: v[x] for x in ("name", "emoji", "req", "on", "f", "p")}
                 for k, v in E.IMPR.items()},
        "res": {k: {"emoji": v["emoji"], "name": v["name"]} for k, v in E.RESOURCES.items()},
        "nwonders": {k: {"name": v["name"], "emoji": v["emoji"], "desc": v["desc"]}
                     for k, v in E.NWONDERS.items()},
        "techs": {k: {"name": v["name"], "cost": v["cost"], "req": v["req"], "note": v.get("note", ""),
                      "unlocks": E.unlocks(k)}
                  for k, v in E.TECHS.items()},
        "blds": {k: {"name": v["name"], "cost": v["cost"], "req": v["req"]}
                 for k, v in E.BUILDINGS.items()},
        "wonders": {k: {"name": v["name"], "cost": v["cost"], "req": v["req"]}
                    for k, v in E.WONDERS.items()},
        "beliefs": {k: list(v) for k, v in E.BELIEFS.items()},
        "levels": E.CITY_LEVELS,
        "cs_kinds": E.CS_KINDS,
        "cs_ally_min": E.CS_ALLY_MIN, "cs_gift": E.CS_GIFT, "cs_gift_inf": E.CS_GIFT_INF,
        "cs_peace_cost": E.CS_PEACE_COST,
        "unit_res": E.UNIT_RES,
        "upgrades": E.UPGRADES,
        "max_turns": E.MAX_TURNS,
        "barb_camp_gold": E.BARB_CAMP_GOLD,
        "version": E.GAME_VERSION,
    }


def meta_payload():
    return _meta()


def setup(app, *, token, load, save, run_turn, bot=None, solo=False):
    DIR = {v: k for k, v in E.DIRS.items()}      # (dx, dy) -> "N"/"S"/"W"/"E"

    def chat_id(v):
        try:
            return int(v)
        except (TypeError, ValueError):
            raise _fail(web.HTTPBadRequest, "Не указан чат")

    def auth(request, chat):
        if solo:
            s = load("solo")
            if not s or not s["started"]:
                raise _fail(web.HTTPNotFound, "Игра не создана")
            return "me", s
        d = check_init_data(request.headers.get("X-Init-Data", ""), token)
        if not d:
            raise _fail(web.HTTPUnauthorized, "Откройте игру из Telegram")
        try:
            uid = str(json.loads(d["user"])["id"])
        except (KeyError, ValueError):
            raise _fail(web.HTTPUnauthorized, "Нет данных пользователя")
        s = load(chat)
        if not s or not s["started"]:
            raise _fail(web.HTTPNotFound, "В этом чате нет идущей игры")
        if uid not in s["players"]:
            raise _fail(web.HTTPForbidden, "Вы не участник этой игры")
        return uid, s

    async def page(_request):
        return web.FileResponse(os.path.join(WEB_DIR, "index.html"),
                                headers={"Cache-Control": "no-cache"})

    async def meta(_request):
        return web.json_response(meta_payload())

    async def state(request):
        uid, s = auth(request, "solo" if solo else chat_id(request.query.get("chat")))
        v = E.view(s, uid)
        v["hints"] = H.hints(s, uid, limit=3) if s["players"][uid].get("hints", True) else []
        return web.json_response(v)

    async def newgame(request):
        if not solo:
            raise _fail(web.HTTPForbidden, "Недоступно")
        try:
            body = await request.json()
        except ValueError:
            body = {}
        import ai
        s = E.new_game("me")
        E.add_player(s, "me", str(body.get("name") or "Вы")[:24])
        n = max(1, min(3, int(body.get("ais", 1))))
        used = {p["name"] for p in s["players"].values()}
        for name in ai.AI_NAMES:
            if len([p for p in s["players"].values() if p.get("ai")]) >= n:
                break
            if name not in used:
                E.add_ai(s, name)
        try:
            E.set_difficulty(s, body.get("difficulty", "normal"))
        except E.GameError:
            pass
        E.start(s)
        s["pub"] = ai.play_all(s)
        save("solo", s)
        return web.json_response({"state": E.view(s, "me")})

    async def act(request):
        try:
            body = await request.json()
        except ValueError:
            raise _fail(web.HTTPBadRequest, "Неверный запрос")
        chat = "solo" if solo else chat_id(body.get("chat"))
        uid, s = auth(request, chat)      # дальше до save() нет await — гонок нет
        if s["winner"]:
            raise _fail(web.HTTPBadRequest, "Игра окончена")
        a = body.get("action")
        public = None
        try:
            if a == "move":
                i = str(body["unit"])
                u = E.own_unit(s, uid, i)
                d = DIR.get((int(body["x"]) - u["x"], int(body["y"]) - u["y"]))
                if not d:
                    raise E.GameError("Ходить можно только на соседнюю клетку")
                u["auto"] = False
                msg = E.move_unit(s, uid, i, d)
            elif a == "found":
                msg = E.found_city(s, uid, str(body["unit"]))
            elif a == "build":
                msg = E.set_build(s, uid, str(body["city"]), str(body["item"]))
            elif a == "buy":
                msg = E.buy(s, uid, str(body["city"]))
            elif a == "research":
                msg = E.set_research(s, uid, str(body["tech"]))
            elif a == "job":
                u = E.own_unit(s, uid, str(body["unit"]))
                u["auto"] = False
                msg = E.start_job(s, uid, str(body["unit"]), str(body["job"]))
            elif a == "upgrade":
                u = E.own_unit(s, uid, str(body["unit"]))
                u["auto"] = False
                msg = E.upgrade_unit(s, uid, str(body["unit"]))
            elif a == "fortify":
                u = E.own_unit(s, uid, str(body["unit"]))
                u["auto"] = False
                msg = E.fortify(s, uid, str(body["unit"]))
            elif a == "disband":
                msg = E.disband(s, uid, str(body["unit"]))
            elif a == "auto":
                import ai
                u = E.own_unit(s, uid, str(body["unit"]))
                if u["type"] not in ("worker", "scout"):
                    raise E.GameError("Автоматизировать можно рабочих и разведчиков")
                u["auto"] = not u.get("auto")
                if u["auto"] and not ai.auto_step(s, uid, str(body["unit"])):
                    u["auto"] = False
                    msg = "Пока нечего делать — автомат отключён"
                else:
                    msg = "🤖 Автоматический режим включён" if u["auto"] else "Автомат отключён"
            elif a == "preach":
                msg = E.preach(s, uid, str(body["unit"]), str(body["city"]))
            elif a == "religion":
                msg, public = E.found_religion(s, uid, str(body["belief"]))
            elif a == "ranged":
                u = E.own_unit(s, uid, str(body["unit"]))
                u["auto"] = False
                msg = E.ranged_attack(s, uid, str(body["unit"]), int(body["x"]), int(body["y"]))
            elif a == "strike":
                msg = E.city_strike(s, uid, str(body["city"]), int(body["x"]), int(body["y"]))
            elif a == "war":
                msg, public = E.declare_war(s, uid, str(body["player"]))
            elif a == "peace":
                msg, public = E.propose_peace(s, uid, str(body["player"]))
            elif a == "accept":
                msg, public = E.accept_peace(s, uid, str(body["player"]))
            elif a == "csgift":
                msg = E.cs_gift(s, uid, str(body["cs"]))
            elif a == "cswar":
                msg, public = E.cs_declare_war(s, uid, str(body["cs"]))
            elif a == "cspeace":
                msg = E.cs_make_peace(s, uid, str(body["cs"]))
            elif a == "end":
                if solo:
                    await run_turn(bot, chat, s)      # сам сохранит состояние
                    msg = "Новый ход!"
                    return web.json_response({"msg": msg, "state": E.view(s, uid)})
                if E.set_ready(s, uid):
                    await run_turn(bot, chat, s)      # сам сохранит состояние
                    msg = "Новый ход!"
                else:
                    save(chat, s)
                    msg = "Ход завершён. Ждём остальных."
                return web.json_response({"msg": msg, "state": E.view(s, uid)})
            else:
                raise E.GameError("Неизвестное действие")
        except E.GameError as e:
            raise _fail(web.HTTPBadRequest, str(e))
        except (KeyError, ValueError, TypeError):
            raise _fail(web.HTTPBadRequest, "Неверный запрос")
        if public:
            s.setdefault("pub", []).append(public)
            if bot:
                try:
                    await bot.send_message(chat, public)
                except Exception:
                    pass
        save(chat, s)
        return web.json_response({"msg": msg, "state": E.view(s, uid)})

    async def savefile(_request):
        if not solo:
            raise _fail(web.HTTPForbidden, "Недоступно")
        s = load("solo")
        if not s:
            raise _fail(web.HTTPNotFound, "Нет игры")
        return web.json_response(s)

    if solo:
        app.router.add_get("/", page)
        app.router.add_post("/api/newgame", newgame)
        app.router.add_get("/api/savefile", savefile)
    app.router.add_get("/app", page)
    app.router.add_get("/api/meta", meta)
    app.router.add_get("/api/state", state)
    app.router.add_post("/api/act", act)
