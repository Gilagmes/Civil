"""Telegram-бот «Цивилизация». Запуск: python bot.py  (нужна переменная BOT_TOKEN)."""
import asyncio
import html
import io
import json
import logging
import os
import sqlite3
import time

from aiogram import Bot, Dispatcher, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command
from aiogram.types import (BotCommand, BufferedInputFile, CallbackQuery,
                           InlineKeyboardButton as B, InlineKeyboardMarkup, Message)
from aiohttp import web

import ai
import engine as E
import hints
import mapimg
import webapi


def _load_env():
    """Читает файл .env рядом с bot.py (строки вида BOT_TOKEN=...), если он есть."""
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
    if os.path.exists(path):
        for line in open(path, encoding="utf-8"):
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip().strip("\"'"))


_load_env()
TOKEN = os.environ["BOT_TOKEN"]
TURN_HOURS = float(os.getenv("TURN_HOURS", "24"))   # длительность хода в часах
DB_PATH = os.getenv("DB_PATH", "civ.db")
MINIAPP = os.getenv("MINIAPP_LINK", "")             # https://t.me/ИМЯ_БОТА/play

db = sqlite3.connect(DB_PATH, check_same_thread=False)
db.execute("create table if not exists games (chat_id integer primary key, state text not null)")
db.execute("create table if not exists snapshots (chat_id integer, turn integer, ts real, state text, "
           "primary key (chat_id, turn))")
db.execute("create table if not exists stats (chat_id integer, user_id text, name text, games integer default 0, "
           "wins integer default 0, human_games integer default 0, human_wins integer default 0, "
           "best_score integer default 0, primary key (chat_id, user_id))")
db.execute("create table if not exists history (id integer primary key autoincrement, chat_id integer, "
           "ended real, turns integer, winner text, reason text, summary text)")
db.commit()
router = Router()


def load(chat):
    r = db.execute("select state from games where chat_id=?", (chat,)).fetchone()
    if not r:
        return None
    s = json.loads(r[0])
    return s if s.get("ver") == E.VER else None   # старые сохранения несовместимы


def save(chat, s):
    db.execute("insert or replace into games values (?,?)", (chat, json.dumps(s, ensure_ascii=False)))
    db.commit()


def snapshot(chat, s):
    """Копия состояния в начале хода (хранятся последние 6) — для /rollback."""
    db.execute("insert or replace into snapshots values (?,?,?,?)",
               (chat, s["turn"], time.time(), json.dumps(s, ensure_ascii=False)))
    db.execute("delete from snapshots where chat_id=? and turn < ?", (chat, s["turn"] - 5))
    db.commit()


def backup_db():
    """Копия всей базы в файл <база>.bak (через встроенный механизм sqlite — безопасно при работе)."""
    dst = sqlite3.connect(DB_PATH + ".bak")
    try:
        db.backup(dst)
    finally:
        dst.close()


def final_summary(s):
    lines = ["📊 Итоги партии:"]
    for k, p in sorted(s["players"].items(), key=lambda kv: -E.score(s, kv[0])):
        cs = [c for c in s["cities"].values() if c["owner"] == k]
        lines.append(f"{'🏆 ' if k == s['winner'] else ''}{p['name']}{' 🤖' if p.get('ai') else ''}: "
                     f"очки {E.score(s, k)} · городов {len(cs)} · технологий {len(p['techs'])}/{len(E.TECHS)} · "
                     f"чудес {sum(len(c['wonders']) for c in cs)}" + ("" if p["alive"] else " · выбыл"))
    return "\n".join(lines)


def record_result(chat, s):
    """Записывает итоги законченной партии в статистику чата и в историю."""
    humans = [(k, p) for k, p in s["players"].items() if not p.get("ai")]
    multi = len(humans) >= 2
    for k, p in humans:
        won = s["winner"] == k
        db.execute("insert or ignore into stats (chat_id, user_id, name) values (?,?,?)", (chat, k, p["name"]))
        db.execute("update stats set name=?, games=games+1, wins=wins+?, human_games=human_games+?, "
                   "human_wins=human_wins+?, best_score=max(best_score, ?) where chat_id=? and user_id=?",
                   (p["name"], int(won), int(multi), int(won and multi), E.score(s, k), chat, k))
    wname = s["players"][s["winner"]]["name"] if s["winner"] in s["players"] else "—"
    db.execute("insert into history (chat_id, ended, turns, winner, reason, summary) values (?,?,?,?,?,?)",
               (chat, time.time(), s["turn"], wname, E.WIN_REASON.get(s["win_reason"], "—"), final_summary(s)))
    db.commit()


def validate_state(s):
    """Проверка файла сохранения: бросает исключение, если он испорчен или от другой версии."""
    if s.get("ver") != E.VER:
        raise ValueError("файл от другой версии игры")
    if len(s["map"]) != E.H or len(s["map"][0]) != E.W:
        raise ValueError("размер карты не совпадает")
    if not s["players"]:
        raise ValueError("в игре нет игроков")
    for k in s["players"]:
        E.render_map(s, k)
    E.legend(s)


def kb(rows):
    return InlineKeyboardMarkup(inline_keyboard=rows)


def back(cb_data="main", text="◀️ Меню"):
    return [B(text=text, callback_data=cb_data)]


# ---------- экраны ----------

def head(s, uid):
    p = s["players"][uid]
    return f"{E.CIRCLES[p['color']]} {p['name']} · ход {s['turn']}/{E.MAX_TURNS} · 💰{p['gold']}"


def view_main(s, uid):
    p = s["players"][uid]
    res = "не выбрано"
    if p["research"]:
        t = E.TECHS[p["research"]]
        res = f"{t['name']} ({p['progress']}/{t['cost']})"
    waiting = [q["name"] for q in s["players"].values() if q["alive"] and not q["ready"]]
    state = "✅ Вы завершили ход" if p["ready"] else "⏳ Ход ещё не завершён"
    if p["ready"] and waiting:
        state += f" (ждём: {', '.join(waiting)})"
    left = ""
    if s.get("deadline"):
        m = max(0, int((s["deadline"] - time.time()) // 60))
        left = f" · ⏱ {m // 60}ч {m % 60}м"
    text = (f"{head(s, uid)} ({E.income(s, uid):+d}/ход){left}\n\n{E.render_map(s, uid)}\n"
            "⬛ неизвестно  ⚫ варвары  🛖 селение  🏯 город-государство\n\n"
            f"{E.legend(s)}\n\n🔬 Исследование: {res}\n{state}")
    res = E.resources_of(s, uid)
    if any(res.values()):
        text += "\n" + "  ".join(f"{E.RESOURCES[r]['emoji']}{n}" for r, n in res.items() if n)
    if p.get("religion"):
        text += f"\n🕊 {s['religions'][p['religion']]['name']} · вера {p.get('faith', 0)}"
    else:
        text += f"\n🕊 Вера: {p.get('faith', 0)}/{E.FAITH_NEED}"
    if p.get("hints", True):
        hs = hints.hints(s, uid)
        if hs:
            text += "\n\n" + "\n".join("💡 " + h for h in hs)
    if p["news"]:
        text += "\n\n📰 Новости:\n" + "\n".join(p["news"][-8:])
    rows = [[B(text="🪖 Юниты", callback_data="us"), B(text="🏙 Города", callback_data="cs")],
            [B(text="🔬 Наука", callback_data="ts"), B(text="🎭 Институты", callback_data="cv")],
            [B(text="🤝 Дипломатия", callback_data="dp"), B(text="🕊 Религия", callback_data="rl")],
            [B(text="🖼 Карта картинкой", callback_data="img")],
            [B(text="🔄 Обновить", callback_data="main")],
            [B(text="✅ Завершить ход", callback_data="end")]]
    return text, kb(rows)


def unit_label(i, u):
    t = E.UNITS[u["type"]]
    extra = (" 🛡" if u["fort"] else "") + (" 🐫" if u["job"] == "route" else " 🔨" if u["job"] else "") \
        + (" 🤖" if u.get("auto") else "")
    extra += "⭐" * E.promo_level(u)
    ship = " ⛵" if t.get("naval") else (" ⛵на борту" if u.get("aboard") else "")
    return f"{t['name']} #{i} ({u['x']},{u['y']}) ❤{u['hp']} 🦶{u['mv']:g}{extra}{ship}"


def view_units(s, uid):
    rows = [[B(text=unit_label(i, u), callback_data=f"u:{i}")]
            for i, u in s["units"].items() if u["owner"] == uid]
    empty = not rows
    rows.append(back())
    text = f"{head(s, uid)}\n\n" + ("Юнитов нет." if empty else "Ваши юниты (🦶 — осталось движения, 🛡 укреплён, 🔨 работает):")
    return text, kb(rows)


def view_unit(s, uid, i):
    u = E.own_unit(s, uid, i)
    t = E.TERRAIN[s["map"][u["y"]][u["x"]]]
    ut = E.UNITS[u["type"]]
    info = f"⚔{ut['att']} 🛡{ut['def']}" if ut["def"] or ut["att"] else "мирный"
    job = ""
    if u["job"]:
        job = f"\n🔨 {E.job_info(u['job'])[0]}: осталось {u['left']} хода"
    if ut.get("naval"):
        job += f"\n⛵ На борту: {E._cargo(s, i)}/{ut['cap']} (загрузка: сухопутный юнит идёт на клетку с галерой)"
    elif u.get("aboard"):
        job += "\n⛵ На борту галеры: чтобы высадиться, идите на свободный берег"
    text = (f"{head(s, uid)}\n\n{E.render_map(s, uid, (u['x'], u['y']))}\n\n"
            f"⭐ {ut['name']} #{i} ({u['x']},{u['y']}), {t['name']}\n"
            f"❤{u['hp']}  {info}  🦶 движения: {u['mv']:g}/{ut['moves']}{job}")
    rows = [[B(text="⬆️", callback_data=f"m:{i}:N")],
            [B(text="⬅️", callback_data=f"m:{i}:W"), B(text="➡️", callback_data=f"m:{i}:E")],
            [B(text="⬇️", callback_data=f"m:{i}:S")]]
    if u["type"] == "settler":
        rows.append([B(text="🏙 Основать город", callback_data=f"f:{i}")])
    if u["type"] == "worker":
        terr = s["map"][u["y"]][u["x"]]
        techs = s["players"][uid]["techs"]
        for k, im in E.IMPR.items():
            if im["on"] == terr and im["req"] in techs and f"{u['x']},{u['y']}" not in s["impr"] \
                    and not E.city_at(s, u["x"], u["y"]):
                rows.append([B(text=f"{im['emoji']} Построить: {im['name']}", callback_data=f"j:{i}:{k}")])
        if "wheel" in techs and terr != "water" and not E.has_road(s, u["x"], u["y"]):
            rows.append([B(text="🛤 Построить дорогу", callback_data=f"j:{i}:road")])
    if u["type"] == "missionary":
        for cid, c in E.preach_targets(s, uid, i):
            rows.append([B(text=f"📿 Проповедовать: {c['name']}", callback_data=f"pr:{i}:{cid}")])
        job += "\n📿 Подойдите к городу вплотную (можно и к чужому) и выберите «Проповедовать»: город примет вашу веру, миссионер расходуется."
    if u["type"] == "trader":
        dests = E.route_dests(s, uid, i)
        for d in dests[:5]:
            rows.append([B(text=f"🐫 Путь в {d['name']} (+{d['gold']}💰 +{d['food']}🌾)",
                           callback_data=f"rt:{i}:{d['id']}")])
        if u["job"] == "route":
            rid = next((rid for rid, r in s.get("routes", {}).items() if r["uid"] == i), None)
            if rid:
                rows.append([B(text="🛑 Отозвать караван", callback_data=f"rc:{rid}")])
        elif not dests:
            job += "\n🐫 Поставьте караван в свой город и откройте путь в другой свой город: золото и еда каждый ход."
    if ut.get("range"):
        targets = [(i2, v) for i2, v in s["units"].items()
                   if v["owner"] != uid and E.relation(s, uid, v["owner"]) == "war"
                   and E.dist((u["x"], u["y"]), (v["x"], v["y"])) <= ut["range"]][:6]
        for i2, v in targets:
            rows.append([B(text=f"🎯 Обстрелять: {E.UNITS[v['type']]['name']} ({v['x']},{v['y']})",
                           callback_data=f"ra:{i}:{i2}")])
    to = E.UPGRADES.get(u["type"])
    if to:
        rows.append([B(text=f"⬆ Улучшить: {E.UNITS[to]['name']} за {E.upgrade_price(u['type'], to)}💰",
                       callback_data=f"up:{i}")])
    if ut["def"] > 0:
        rows.append([B(text="🛡 Укрепиться", callback_data=f"fo:{i}")])
    if u["type"] in ("worker", "scout"):
        rows.append([B(text=("⏹ Отключить автомат" if u.get("auto") else
                             "🤖 Автоматически: " + ("исследовать" if u["type"] == "scout" else "улучшать землю")),
                       callback_data=f"au:{i}")])
    rows.append([B(text="❌ Распустить", callback_data=f"x:{i}")])
    rows.append(back("us", "◀️ Юниты"))
    return text, kb(rows)


def view_cities(s, uid):
    rows = [[B(text=f"{'⭐ ' if c['capital'] else ''}{c['name']} (нас. {c['pop']})", callback_data=f"c:{i}")]
            for i, c in s["cities"].items() if c["owner"] == uid]
    empty = not rows
    rows.append(back())
    text = f"{head(s, uid)}\n\n" + ("Городов нет. Основайте город поселенцем (меню «Юниты»)." if empty else "Ваши города:")
    return text, kb(rows)


def item_label(item):
    d = E.item_data(item)
    return d["name"], d["cost"]


def view_city(s, uid, cid):
    c = E.own_city(s, uid, cid)
    f, p, sci, g = E.city_yields(s, c)
    building = "ничего"
    if c["build"]:
        n, cost = item_label(c["build"])
        building = f"{n} ({c['prod']}/{cost})"
    bl = ", ".join(E.BUILDINGS[b]["name"].split(" (")[0] for b in c["buildings"]) or "нет"
    wl = ", ".join(E.WONDERS[w]["name"].split(" (")[0] for w in c["wonders"]) or "нет"
    lvl = E.city_level(c)
    nxt = (f" (следующий уровень при населении {E.CITY_LEVELS[lvl][0]})" if lvl < len(E.CITY_LEVELS) else " (максимум)")
    text = (f"{head(s, uid)}\n\n{'⭐ ' if c['capital'] else ''}{c['name']} ({c['x']},{c['y']}) — {E.city_level_name(c)}{nxt}\n"
            f"Население: {c['pop']} (рост {c['food']}/{E.food_need(c)}, {f - 2 * c['pop']:+d}🌾/ход)\n"
            f"⚙️ {p}/ход   🔬 {sci}/ход   💰 {g}/ход\n"
            f"🎭 Культура: {c.get('culture', 0)} (радиус границ: {E.border_radius(c)})\n"
            f"Постройки: {bl}\nЧудеса: {wl}\nСтроится: {building}")
    if not c["capital"] and "wheel" in s["players"][uid]["techs"]:
        text += (f"\n🛤 Дорога до столицы: соединён (+{E.ROAD_LINK_GOLD}💰)" if E.road_connected(s, c)
                 else f"\n🛤 Дороги до столицы нет (соединение даёт +{E.ROAD_LINK_GOLD}💰/ход)")
    rows = []
    if c.get("struck") != s["turn"]:
        targets = [(i2, v) for i2, v in s["units"].items()
                   if v["owner"] != uid and E.relation(s, uid, v["owner"]) == "war"
                   and E.dist((c["x"], c["y"]), (v["x"], v["y"])) <= 2][:6]
        for i2, v in targets:
            rows.append([B(text=f"🎯 Обстрел из города: {E.UNITS[v['type']]['name']} ({v['x']},{v['y']})",
                           callback_data=f"st:{cid}:{i2}")])
    rows.append([B(text="🔨 Что строить", callback_data=f"bs:{cid}")])
    price = E.buy_price(s, c)
    if price:
        rows.append([B(text=f"💰 Купить за {price}", callback_data=f"by:{cid}")])
    rows.append(back("cs", "◀️ Города"))
    return text, kb(rows)


def view_build(s, uid, cid):
    c = E.own_city(s, uid, cid)
    rows = [[B(text=f"{n} — {cost}⚙️", callback_data=f"b:{cid}:{item}")]
            for item, n, cost in E.available_items(s, uid, c)]
    rows.append(back(f"c:{cid}", "◀️ Город"))
    text = (f"{head(s, uid)}\n\n{c['name']}: что строить? (🏛 — чудо света, одно на весь мир; "
            "строится в городах с населением от 3)")
    locked = E.locked_units(s, uid)
    if locked:
        text += "\n\n🔒 Нужен ресурс в вашей земле: " + ", ".join(f"{n} ({e} {r})" for n, e, r in locked)
    return text, kb(rows)


def view_tech(s, uid):
    p = s["players"][uid]
    av = E.available_techs(s, uid)
    known = ", ".join(E.TECHS[k]["name"] for k in p["techs"]) or "нет"
    lines = [f"• {E.TECHS[k]['name']} — {E.TECHS[k]['cost']}🔬: {E.unlocks(k)}" for k in av]
    text = (f"{head(s, uid)}\n\nИзучено ({len(p['techs'])}/{len(E.TECHS)}): {known}\n\n"
            + ("Доступно:\n" + "\n".join(lines) if av else "Все доступные технологии изучены.")
            + "\n\nИзучите все технологии — и вы выиграете научной победой!")
    rows = [[B(text=f"{E.TECHS[k]['name']} — {E.TECHS[k]['cost']}🔬", callback_data=f"t:{k}")] for k in av]
    rows.append(back())
    return text, kb(rows)


def view_diplo(s, uid):
    lines, rows = [], []
    for k, q in s["players"].items():
        if k == uid or not q["alive"]:
            continue
        war = E.relation(s, uid, k) == "war"
        lines.append(f"{E.SQUARES[q['color']]} {q['name']}: {'⚔️ война' if war else '🕊 мир'}")
        if not war:
            rows.append([B(text=f"⚔️ Объявить войну: {q['name']}", callback_data=f"dw:{k}")])
        elif [k, uid] in s["offers"]:
            rows.append([B(text=f"🕊 Принять мир: {q['name']}", callback_data=f"ap:{k}")])
        elif [uid, k] in s["offers"]:
            lines.append("   ⏳ вы предложили мир, ждём ответа")
        else:
            rows.append([B(text=f"🕊 Предложить мир: {q['name']}", callback_data=f"pp:{k}")])
    seen = s["players"][uid]["seen"]
    cs_lines = []
    for csid, cs in s.get("cstates", {}).items():
        if not seen[cs["y"] * E.W + cs["x"]]:
            continue          # найдите город-государство разведкой
        inf = cs["inf"].get(uid, 0)
        ally = cs.get("ally")
        who = f", союзник: {s['players'][ally]['name']}" if ally else ""
        at_war = uid in cs["war"]
        st = "⚔️ война" if at_war else f"влияние {inf}/{E.CS_ALLY_MIN}"
        cs_lines.append(f"🏯 {cs['name']} ({cs['x']},{cs['y']}) — {E.CS_KINDS[cs['kind']]}\n   {st}{who}")
        if at_war:
            rows.append([B(text=f"🕊 Мир с {cs['name']} — {E.CS_PEACE_COST}💰", callback_data=f"gp:{csid}")])
        else:
            rows.append([B(text=f"🎁 {cs['name']}: подарок {E.CS_GIFT}💰", callback_data=f"g:{csid}"),
                         B(text="⚔️", callback_data=f"gw:{csid}")])
    rows.append(back())
    text = f"{head(s, uid)}\n\nДипломатия:\n" + ("\n".join(lines) if lines else "Других игроков нет.")
    text += "\n\nПока вы в мире, атаковать нельзя."
    text += "\n\n🏯 Города-государства:\n" + ("\n".join(cs_lines) if cs_lines else "пока не найдены — исследуйте карту")
    if cs_lines:
        text += (f"\nДарите золото, чтобы стать союзником (влияние ≥ {E.CS_ALLY_MIN} и больше, чем у других). "
                 "Влияние падает на 1 за ход. Кнопка ⚔️ — напасть и захватить город.")
    return text, kb(rows)


async def send_map(msg, s, uid):
    """Отправляет карту картинкой; если нет Pillow — эмодзи-картой."""
    caption = E.legend(s)[:900] + "\n🏯 город-государство · цветная граница — территория города"
    png = mapimg.render_png(s, uid)
    if png:
        await msg.answer_photo(BufferedInputFile(png, filename="map.png"), caption=caption)
    else:
        await msg.answer(f"{E.render_map(s, uid)}\n\n{E.legend(s)}")


def view_religion(s, uid):
    p = s["players"][uid]
    lines = [f"Вера: {p.get('faith', 0)} (+1 за город, +2 за храм, +3 за чудо в ход)"]
    rows = []
    if p.get("religion"):
        rel = s["religions"][p["religion"]]
        em, nm, desc = E.BELIEFS[rel["belief"]]
        lines.append(f"Ваша религия: «{rel['name']}» — {nm} ({desc}). Вера сама распространяется на города "
                     f"в радиусе {E.SPREAD_RANGE}; за каждый чужой город верующих вы получаете +1💰/ход.")
    elif E.can_found_religion(s, uid):
        lines.append("Можно основать религию! Выберите верование:")
        for k, (em, nm, desc) in E.BELIEFS.items():
            rows.append([B(text=f"{em} {nm}: {desc}", callback_data=f"rf:{k}")])
    else:
        need = []
        if p.get("faith", 0) < E.FAITH_NEED:
            need.append(f"накопить {E.FAITH_NEED} веры")
        if not any(c["owner"] == uid and "temple" in c["buildings"] for c in s["cities"].values()):
            need.append("построить Храм (нужна Письменность)")
        if len(s.get("religions", {})) >= len(E.RELIGION_NAMES):
            need = ["свободных религий не осталось"]
        lines.append("Чтобы основать религию: " + ", ".join(need) + ".")
    rels = s.get("religions", {})
    if rels:
        share = E.religion_share(s)
        lines.append(f"\n🏆 Религиозная победа: религия в ≥{int(E.REL_WIN_SHARE * 100)}% городов мира "
                     f"(минимум {E.REL_WIN_MIN_CITIES} городов) {E.REL_WIN_TURNS} хода подряд.")
        hold = s.get("rel_hold") or {}
        if hold:
            lines.append(f"⏳ Сейчас лидирует «{rels[hold['rid']]['name']}»: держится {hold['n']}/{E.REL_WIN_TURNS}")
        lines.append("\nРелигии мира:")
        for rid, rel in rels.items():
            n = sum(1 for c in s["cities"].values() if c.get("religion") == rid)
            lines.append(f"• «{rel['name']}» — {s['players'][rel['founder']]['name']}, "
                         f"{E.BELIEFS[rel['belief']][1]}, городов верующих: {n}/{share[rid][1]}")
    rows.append(back())
    return f"{head(s, uid)}\n\n" + "\n".join(lines), kb(rows)


def view_civics(s, uid):
    p = s["players"][uid]
    cult = E.culture_turn(s, uid)
    lines = [f"🎭 Культура: {cult} в ход (по городам; институты изучаются за неё)"]
    rows = []
    done = p.get("civics", [])
    cv = p.get("civic")
    if cv:
        lines.append(f"⏳ Изучаем: «{E.CIVICS[cv]['name']}» — {p.get('cprogress', 0)}/{E.CIVICS[cv]['cost']}🎭")
    av = E.available_civics(s, uid)
    if av:
        lines.append("\nДоступные институты:")
        for k, c in av.items():
            mark = " ⏳" if k == cv else ""
            rows.append([B(text=f"🎭 {c['name']} ({c['cost']}🎭){mark}", callback_data=f"ci:{k}")])
    if done:
        lines.append("\nПриняты: " + ", ".join(f"«{E.CIVICS[k]['name']}»" for k in done))
    if "polphil" in done:
        lines.append("\nСтрой государства:")
        for g, (em, nm, note) in E.GOVS.items():
            mark = " ✅" if p.get("gov") == g else ""
            rows.append([B(text=f"{em} {nm}: {note}{mark}", callback_data=f"gv:{g}")])
        if not p.get("gov"):
            lines.append("Строй ещё не выбран.")
    else:
        lines.append("\n🏛 Строй государства откроется после института «Политическая философия».")
    rows.append(back())
    return f"{head(s, uid)}\n\n" + "\n".join(lines), kb(rows)


async def show(cb, v):
    try:
        await cb.message.edit_text(v[0], reply_markup=v[1])
    except TelegramBadRequest as e:
        if "not modified" not in str(e):
            raise


# ---------- смена хода ----------

def mentions(s, only_waiting=False):
    """Ссылки на людей-игроков (Telegram пришлёт им уведомление)."""
    out = []
    for k, p in s["players"].items():
        if p["alive"] and not p.get("ai") and not (only_waiting and p["ready"]):
            out.append(f'<a href="tg://user?id={k}">{html.escape(p["name"])}</a>')
    return ", ".join(out)


async def run_turn(bot, chat, s):
    pub = E.process_turn(s)
    if not s["winner"]:
        pub += ai.play_all(s)                 # ходят ИИ и автоматические юниты
        s["deadline"] = time.time() + TURN_HOURS * 3600
    s["pub"] = pub                            # публичные события хода для веб-клиента
    if s["winner"] and not s.get("recorded"):
        record_result(chat, s)
        s["recorded"] = True
    save(chat, s)
    snapshot(chat, s)
    text = f"🔔 Начался ход {s['turn']}\n\n" + ("\n".join(pub) + "\n\n" if pub else "") + E.legend(s)
    if s["winner"]:
        if s["winner"] == "none":
            text += "\n\n🏁 Игра окончена: все выбыли."
        else:
            text += (f"\n\n🏆 Победитель: {s['players'][s['winner']]['name']} — "
                     f"{E.WIN_REASON[s['win_reason']]}!")
        text += "\n\n" + final_summary(s) + "\n\nСтатистика: /stats, таблица лидеров: /top"
    else:
        text += "\n\n/menu — ваше меню (там же новости), /play — карта"
    text = html.escape(text)
    if not s["winner"] and mentions(s):
        text += "\n\n👉 " + mentions(s)
    await bot.send_message(chat, text, parse_mode="HTML")


async def ticker(bot):
    last_backup = 0.0
    while True:
        await asyncio.sleep(60)
        if time.time() - last_backup > 86400:
            try:
                backup_db()
                last_backup = time.time()
            except Exception:
                logging.exception("Не удалось сделать копию базы")
        for (chat,) in db.execute("select chat_id from games").fetchall():
            s = load(chat)
            if not (s and s["started"] and not s["winner"] and s["deadline"]):
                continue
            left = s["deadline"] - time.time()
            try:
                if left <= 0:
                    await run_turn(bot, chat, s)
                elif left <= min(2 * 3600, TURN_HOURS * 3600 * 0.25) and s.get("reminded") != s["turn"]:
                    s["reminded"] = s["turn"]
                    save(chat, s)
                    who = mentions(s, only_waiting=True)
                    if who:
                        mins = int(left // 60)
                        await bot.send_message(
                            chat, f"⏰ До конца хода {s['turn']} осталось ~{mins // 60}ч {mins % 60}м. "
                                  f"Ещё не завершили ход: {who}", parse_mode="HTML")
            except Exception:
                logging.exception("Ошибка таймера хода")


# ---------- команды ----------

HELP = ("🏛 Цивилизация\n\n"
        "/newgame — создать игру в этом чате\n"
        "/join — вступить в игру\n"
        "/addai [N] — добавить компьютерных игроков (создатель)\n"
        "/difficulty — сложность ИИ (создатель, до начала)\n"
        "/hints — включить/выключить подсказки в меню\n"
        "/begin — начать игру (создатель)\n"
        "/menu — ваше игровое меню\n"
        "/play — открыть карту (Mini App)\n"
        "/map — ваша карта\n"
        "/rules — правила\n"
        "/stats — ваша статистика, /top — таблица лидеров чата, /history — последние партии\n"
        "/rollback — откат на начало хода (создатель), /export и /import — копия игры файлом\n"
        "/endgame — удалить игру (создатель)")

RULES = ("📜 Правила\n\n"
         "• Карта скрыта туманом ⬛. Юниты и города открывают местность вокруг.\n"
         "• Поселенец основывает город (первый — столица). Города растут, добывают 🌾 еду, ⚙️ производство, 🔬 науку и 💰 золото.\n"
         "• Рабочие строят фермы 🌽 (на равнинах) и шахты 🪨 (на холмах) — 3 хода.\n"
         "• Технологии открываются по дереву: у каждой есть требования. Они дают новых юнитов, здания и чудеса света.\n"
         "• 🏛 Чудо света можно построить только раз в мире — успейте первыми!\n"
         "• 💰 Золото позволяет докупить производство (2💰 за 1⚙️).\n"
         "• Сначала все в мире. Чтобы атаковать, объявите войну (Дипломатия). Мир заключается по согласию обеих сторон.\n"
         "• Бой: юнит бьёт юнита; холмы/леса, города, стены и укрепление усиливают защиту. Катапульты игнорируют стены.\n"
         "• 🎯 Дальний бой (как в Civ 6): лучник и катапульта обстреливают врага в радиусе 2 клеток без ответа; "
         "город тоже стреляет раз в ход (радиус 2). Города захватываются только в ближнем бою.\n"
         "• Город без защитников захватывает любой боевой юнит.\n"
         "• ⚫ Варвары приходят волнами из лагерей 🏕 (после 8 хода) и идут на ближайший город: убивают одиноких юнитов и грабят беззащитные города. Держите гарнизон! За убитого варвара — 10💰, за разорённый лагерь — 20💰.\n"
         "• 🎭 Культура: города копят культуру (храмы, чудеса, население) и расширяют границы. В чужие границы нельзя входить, пока вы в мире; чужие клетки город не обрабатывает.\n"
         "• 🏯 Города-государства (найдите их разведкой): дарите золото, чтобы стать союзником и получать бонусы. Их можно и захватить — но они сильны.\n"
         "• 🐎🔩💎 Ресурсы: Всадникам нужны лошади, Мечникам и Катапультам — железо (они должны лежать в вашей земле или рядом с вашим городом). Самоцветы дают +3💰 в ход.\n"
         "• 🛤 Дороги (технология «Колесо»): движение по дороге стоит в 3 раза меньше. Строят рабочие, 2 хода.\n"
         "• 📿 Основатель религии строит Миссионеров: подойдите к городу вплотную и обратите его. 🏆 Религиозная победа: религия в ≥60% городов мира (при ≥6 городах) 3 хода подряд.\n"
         "• 🕊 Религия: города копят веру (храм и чудеса — больше). Набрав 30 веры при наличии храма, основайте религию с бонусом; вера сама расползается по соседним городам, а вам идёт доход с чужих верующих.\n"
         "• ⛵ Корабли («Мореплавание»): Галеру строят в прибрежных городах. Она перевозит 2 юнита: сухопутный юнит идёт на клетку с галерой, галера плывёт, затем юнит идёт на берег. Галеры топят чужие корабли и обстреливают берег, но города с моря не берут.\n"
         "• 🏘 Уровни городов: Деревня (1–2), Город (3–5: +1⚙️ +1💰), Мегаполис (6+: ещё +1⚙️ +1💰 +2🔬, защита ×1.15). Чудеса строятся в городах с населением от 3.\n"
         "• 💡 В меню есть подсказки, что сделать в этот ход (/hints — выключить).\n"
         "• 🤖 Компьютерные игроки: /addai. Можно играть в одиночку против ИИ. Рабочим и разведчикам доступен автоматический режим.\n"
         "• ⏰ Бот упоминает игроков в начале хода и напоминает перед концом.\n"
         "• 🖼 Карта картинкой: /map или кнопка в меню. 🎮 Интерактивная карта: /play.\n"
         "• 🛖 Селения на карте: зайдите юнитом — получите золото, науку, воина или карту… а иногда засаду варваров.\n"
         "• 🏔 Чудеса природы (Эверест, Озеро Виктория, Килиманджаро, Эльдорадо) дают бонусы клетке или городу, "
         "чьими границами они охвачены.\n"
         "• 🏠 Жильё ограничивает рост: население не растёт выше жилья (2 + амбар + 1 у воды).\n"
         "• ⬆ Юниты улучшаются за золото на своей территории: Воин→Мечник, Лучник→Арбалетчик, "
         "Всадник→Рыцарь (нужны технология и ресурс).\n"
         "• ⭐ Юниты копят опыт в бою: каждые 6 опыта — уровень повышения (до 3, +15% силы за уровень).\n"
         "• 🐫 Караван (нужно «Денежное обращение»): из своего города откройте путь в другой свой город — "
         f"золото и еда каждый ход на {E.TRADE_TURNS} ходов, чем дальше города, тем выгоднее.\n"
         "• 🎭 Культура городов изучает институты (🎭 Институты в меню): бонусы к экономике и армии, "
         "а «Политическая философия» открывает выбор строя — автократия, монархия или республика.\n\n"
         f"🏆 Победа: 1) остаться последним; 2) изучить все технологии; 3) иметь больше всех очков после {E.MAX_TURNS} хода.\n"
         "Очки: города, население, технологии, чудеса, золото.")


@router.message(Command("start", "help"))
async def cmd_help(m: Message):
    await m.answer(HELP)


@router.message(Command("rules"))
async def cmd_rules(m: Message):
    await m.answer(RULES)


@router.message(Command("newgame"))
async def cmd_new(m: Message):
    s = load(m.chat.id)
    if s and not s["winner"]:
        return await m.answer("В этом чате уже есть игра. Удалить её: /endgame (создатель).")
    s = E.new_game(m.from_user.id)
    E.add_player(s, m.from_user.id, m.from_user.full_name)
    save(m.chat.id, s)
    await m.answer("🏛 Игра создана! Остальные вступают командой /join.\n"
                   f"Когда все в сборе, создатель пишет /begin (до {E.MAX_PLAYERS} игроков). Правила: /rules")


@router.message(Command("join"))
async def cmd_join(m: Message):
    s = load(m.chat.id)
    if not s:
        return await m.answer("Сначала /newgame")
    try:
        E.add_player(s, m.from_user.id, m.from_user.full_name)
    except E.GameError as e:
        return await m.answer(str(e))
    save(m.chat.id, s)
    await m.answer(f"✅ {m.from_user.full_name} в игре. Игроков: {len(s['players'])}")


@router.message(Command("addai"))
async def cmd_addai(m: Message):
    s = load(m.chat.id)
    if not s:
        return await m.answer("Сначала /newgame")
    if str(m.from_user.id) != s["owner"]:
        return await m.answer("Добавлять компьютерных игроков может только создатель.")
    parts = (m.text or "").split()
    n = int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else 1
    added = []
    try:
        for _ in range(max(1, min(n, 5))):
            used = {p["name"] for p in s["players"].values()}
            name = next((x for x in ai.AI_NAMES if x not in used), f"Компьютер {len(s['players'])}")
            E.add_ai(s, name)
            added.append(name)
    except E.GameError as e:
        if not added:
            return await m.answer(str(e))
    save(m.chat.id, s)
    await m.answer(f"🤖 Добавлено компьютерных игроков: {', '.join(added)}. Всего игроков: {len(s['players'])}")


DIFF_ALIASES = {"easy": "easy", "лёгкий": "easy", "легкий": "easy", "1": "easy",
                "normal": "normal", "обычный": "normal", "2": "normal",
                "hard": "hard", "трудный": "hard", "3": "hard"}


@router.message(Command("difficulty"))
async def cmd_difficulty(m: Message):
    s = load(m.chat.id)
    if not s:
        return await m.answer("Сначала /newgame")
    parts = (m.text or "").split()
    cur = E.DIFFICULTY[E.difficulty(s)]["name"]
    if len(parts) < 2:
        return await m.answer(f"Сложность компьютерных игроков: {cur}.\n"
                              "Изменить (создатель, до /begin): /difficulty лёгкий | обычный | трудный")
    if str(m.from_user.id) != s["owner"]:
        return await m.answer("Менять сложность может только создатель.")
    level = DIFF_ALIASES.get(parts[1].lower())
    if not level:
        return await m.answer("Сложность: лёгкий, обычный или трудный")
    try:
        E.set_difficulty(s, level)
    except E.GameError as e:
        return await m.answer(str(e))
    save(m.chat.id, s)
    note = {"easy": "ИИ миролюбив и развивается медленнее.", "normal": "ИИ играет на равных.",
            "hard": "ИИ агрессивнее, расширяется активнее и получает +30% к производству, науке и золоту."}[level]
    await m.answer(f"⚙️ Сложность: {E.DIFFICULTY[level]['name']}. {note}")


@router.message(Command("hints"))
async def cmd_hints(m: Message):
    s = load(m.chat.id)
    uid = str(m.from_user.id)
    if not s or uid not in s["players"]:
        return await m.answer("Вы не участник этой игры.")
    p = s["players"][uid]
    p["hints"] = not p.get("hints", True)
    save(m.chat.id, s)
    await m.answer("💡 Подсказки в меню " + ("включены" if p["hints"] else "выключены") + ". Переключить: /hints")


@router.message(Command("begin"))
async def cmd_begin(m: Message):
    s = load(m.chat.id)
    if not s:
        return await m.answer("Сначала /newgame")
    if str(m.from_user.id) != s["owner"]:
        return await m.answer("Начать игру может только создатель.")
    try:
        E.start(s)
    except E.GameError as e:
        return await m.answer(str(e))
    ai.play_all(s)
    s["deadline"] = time.time() + TURN_HOURS * 3600
    save(m.chat.id, s)
    snapshot(m.chat.id, s)
    ai_note = (f"Сложность ИИ: {E.DIFFICULTY[E.difficulty(s)]['name']}\n"
               if any(p.get("ai") for p in s["players"].values()) else "")
    await m.answer(f"🚀 Игра началась!\n\n{E.legend(s)}\n{ai_note}\n"
                   "У каждого есть поселенец, воин и рабочий. Откройте /menu → «Юниты» → поселенец → «Основать город».\n"
                   f"Ход длится {TURN_HOURS:g} ч. или пока все не нажмут «Завершить ход». Правила: /rules")


@router.message(Command("menu"))
async def cmd_menu(m: Message):
    s = load(m.chat.id)
    uid = str(m.from_user.id)
    if not s or not s["started"]:
        return await m.answer("Игра ещё не началась.")
    if uid not in s["players"]:
        return await m.answer("Вы не участник этой игры.")
    v = view_main(s, uid)
    await m.answer(v[0], reply_markup=v[1])


@router.message(Command("play"))
async def cmd_play(m: Message):
    s = load(m.chat.id)
    uid = str(m.from_user.id)
    if not s or not s["started"]:
        return await m.answer("Игра ещё не началась.")
    if uid not in s["players"]:
        return await m.answer("Вы не участник этой игры.")
    if not MINIAPP:
        return await m.answer("Mini App не настроен (задайте переменную MINIAPP_LINK).")
    await m.answer("🎮 Откройте карту:", reply_markup=kb(
        [[B(text="🎮 Играть", url=f"{MINIAPP}?startapp={m.chat.id}")]]))


@router.message(Command("map"))
async def cmd_map(m: Message):
    s = load(m.chat.id)
    uid = str(m.from_user.id)
    if not s or not s["started"] or uid not in s["players"]:
        return await m.answer("Вы не участник идущей игры.")
    await send_map(m, s, uid)


@router.message(Command("stats"))
async def cmd_stats(m: Message):
    r = db.execute("select name, games, wins, human_games, human_wins, best_score from stats "
                   "where chat_id=? and user_id=?", (m.chat.id, str(m.from_user.id))).fetchone()
    if not r or not r[1]:
        return await m.answer("Пока нет законченных партий. Сыграйте — и здесь появится статистика!")
    name, games, wins, hg, hw, best = r
    await m.answer(f"📈 {name}\nПартий: {games}, побед: {wins} ({round(100 * wins / games)}%)\n"
                   f"Против людей: {hg} партий, {hw} побед\nЛучший счёт: {best}\n"
                   f"Рейтинг: {3 * wins + (games - wins)}")


@router.message(Command("top"))
async def cmd_top(m: Message):
    rows = db.execute("select name, games, wins, human_wins from stats where chat_id=? "
                      "order by wins desc, human_wins desc, games asc limit 10", (m.chat.id,)).fetchall()
    if not rows:
        return await m.answer("Таблица лидеров пуста — нет законченных партий.")
    medals = ["🥇", "🥈", "🥉"]
    lines = [f"{medals[i] if i < 3 else str(i + 1) + '.'} {n} — побед {w} из {g} (против людей: {hw})"
             for i, (n, g, w, hw) in enumerate(rows)]
    await m.answer("🏆 Таблица лидеров чата\n" + "\n".join(lines))


@router.message(Command("history"))
async def cmd_history(m: Message):
    rows = db.execute("select ended, turns, winner, reason from history where chat_id=? "
                      "order by id desc limit 5", (m.chat.id,)).fetchall()
    if not rows:
        return await m.answer("Законченных партий пока не было.")
    await m.answer("📜 Последние партии\n" + "\n".join(
        f"{time.strftime('%d.%m', time.localtime(e))}: победил {w} — {r}, ход {t}" for e, t, w, r in rows))


@router.message(Command("rollback"))
async def cmd_rollback(m: Message):
    s = load(m.chat.id)
    if not s or not s["started"]:
        return await m.answer("Игра не идёт.")
    if str(m.from_user.id) != s["owner"]:
        return await m.answer("Откатывать игру может только создатель.")
    if s["winner"]:
        return await m.answer("Игра уже закончена, откат невозможен.")
    turns = [t for (t,) in db.execute("select turn from snapshots where chat_id=? order by turn desc limit 3",
                                      (m.chat.id,)).fetchall()]
    if not turns:
        return await m.answer("Сохранённых копий пока нет.")
    rows = [[B(text=f"↩️ К началу хода {t}" + (" (текущий)" if t == s["turn"] else ""), callback_data=f"rb:{t}")]
            for t in turns] + [[B(text="Отмена", callback_data="rbx")]]
    await m.answer("Откатить игру? Всё, что сделано после выбранного момента, пропадёт (включая ходы других игроков).",
                   reply_markup=kb(rows))


@router.message(Command("export"))
async def cmd_export(m: Message):
    s = load(m.chat.id)
    if not s:
        return await m.answer("Игры нет.")
    if str(m.from_user.id) != s["owner"]:
        return await m.answer("Сохранить копию может только создатель.")
    data = json.dumps(s, ensure_ascii=False).encode("utf-8")
    await m.answer_document(BufferedInputFile(data, filename=f"civ_turn{s['turn']}.json"),
                            caption="💾 Копия игры. Восстановить: ответьте на этот файл командой /import")


@router.message(Command("import"))
async def cmd_import(m: Message):
    doc = m.reply_to_message.document if m.reply_to_message else None
    if not doc:
        return await m.answer("Ответьте командой /import на сообщение с файлом копии игры (.json).")
    if doc.file_size and doc.file_size > 5_000_000:
        return await m.answer("Файл слишком большой.")
    cur = load(m.chat.id)
    if cur and not cur["winner"]:
        if "force" not in (m.text or ""):
            return await m.answer("В этом чате уже идёт игра. Заменить её: /import force (только создатель).")
        if str(m.from_user.id) != cur["owner"]:
            return await m.answer("Заменить игру может только её создатель.")
    try:
        buf = await m.bot.download(doc)
        s = json.loads(buf.read().decode("utf-8"))
        validate_state(s)
    except Exception as e:
        return await m.answer(f"Файл не подходит: {e}")
    uid = str(m.from_user.id)
    if uid not in s["players"] or s["players"][uid].get("ai"):
        return await m.answer("Вы не участник этой игры, восстановить её нельзя.")
    s["owner"] = uid
    s["recorded"] = bool(s["winner"])
    if s["started"] and not s["winner"]:
        s["deadline"] = time.time() + TURN_HOURS * 3600
    save(m.chat.id, s)
    snapshot(m.chat.id, s)
    await m.answer(f"✅ Игра восстановлена: ход {s['turn']}, игроков {len(s['players'])}. Продолжайте: /menu")


@router.message(Command("endgame"))
async def cmd_end(m: Message):
    s = load(m.chat.id)
    if not s:
        return await m.answer("Игры нет.")
    if str(m.from_user.id) != s["owner"]:
        return await m.answer("Удалить игру может только создатель.")
    db.execute("delete from games where chat_id=?", (m.chat.id,))
    db.commit()
    await m.answer("Игра удалена. Новая: /newgame")


# ---------- кнопки ----------

@router.callback_query()
async def on_cb(cb: CallbackQuery):
    chat = cb.message.chat.id
    s = load(chat)
    uid = str(cb.from_user.id)
    if not s or not s["started"]:
        return await cb.answer("Игра не идёт", show_alert=True)
    if uid not in s["players"]:
        return await cb.answer("Вы не участник этой игры", show_alert=True)
    if (cb.data or "") == "rbx":
        await cb.message.edit_text("Откат отменён.")
        return await cb.answer()
    if (cb.data or "").startswith("rb:"):
        if uid != s["owner"] or s["winner"]:
            return await cb.answer("Откатывать может только создатель, пока игра идёт", show_alert=True)
        turn = int(cb.data.split(":")[1])
        r = db.execute("select state from snapshots where chat_id=? and turn=?", (chat, turn)).fetchone()
        if not r:
            return await cb.answer("Копия не найдена", show_alert=True)
        snap = json.loads(r[0])
        snap["deadline"] = time.time() + TURN_HOURS * 3600
        snap.pop("reminded", None)
        save(chat, snap)
        await cb.message.edit_text(f"↩️ Игра возвращена к началу хода {turn}. Откройте /menu.")
        return await cb.answer("Готово")
    if s["winner"]:
        return await cb.answer("Игра окончена", show_alert=True)
    a = (cb.data or "").split(":")
    cmd = a[0]
    if cmd in ("m", "fo", "j", "f") and len(a) > 1 and a[1] in s["units"]:
        s["units"][a[1]]["auto"] = False      # ручная команда отключает автомат
    toast, public = None, None
    try:
        if cmd == "main":
            v = view_main(s, uid)
        elif cmd == "us":
            v = view_units(s, uid)
        elif cmd == "u":
            v = view_unit(s, uid, a[1])
        elif cmd == "m":
            toast = E.move_unit(s, uid, a[1], a[2])
            save(chat, s)
            v = view_unit(s, uid, a[1]) if a[1] in s["units"] else view_units(s, uid)
        elif cmd == "f":
            toast = E.found_city(s, uid, a[1])
            save(chat, s)
            v = view_cities(s, uid)
        elif cmd == "fo":
            toast = E.fortify(s, uid, a[1])
            save(chat, s)
            v = view_unit(s, uid, a[1])
        elif cmd == "ra":
            t = s["units"].get(a[2])
            toast = E.ranged_attack(s, uid, a[1], t["x"], t["y"]) if t else "Цель исчезла"
            save(chat, s)
            v = view_unit(s, uid, a[1]) if a[1] in s["units"] else view_units(s, uid)
        elif cmd == "st":
            t = s["units"].get(a[2])
            toast = E.city_strike(s, uid, a[1], t["x"], t["y"]) if t else "Цель исчезла"
            save(chat, s)
            v = view_city(s, uid, a[1])
        elif cmd == "up":
            toast = E.upgrade_unit(s, uid, a[1])
            save(chat, s)
            v = view_unit(s, uid, a[1])
        elif cmd == "j":
            toast = E.start_job(s, uid, a[1], a[2])
            save(chat, s)
            v = view_unit(s, uid, a[1])
        elif cmd == "pr":
            toast = E.preach(s, uid, a[1], a[2])
            save(chat, s)
            v = view_units(s, uid)
        elif cmd == "rt":
            toast = E.start_route(s, uid, a[1], a[2])
            save(chat, s)
            v = view_unit(s, uid, a[1])
        elif cmd == "rc":
            toast = E.cancel_route(s, uid, a[1])
            save(chat, s)
            v = view_units(s, uid)
        elif cmd == "rl":
            v = view_religion(s, uid)
        elif cmd == "cv":
            v = view_civics(s, uid)
        elif cmd == "ci":
            toast = E.set_civic(s, uid, a[1])
            save(chat, s)
            v = view_civics(s, uid)
        elif cmd == "gv":
            toast = E.set_gov(s, uid, a[1])
            save(chat, s)
            v = view_civics(s, uid)
        elif cmd == "rf":
            toast, public = E.found_religion(s, uid, a[1])
            save(chat, s)
            v = view_religion(s, uid)
        elif cmd == "au":
            u = E.own_unit(s, uid, a[1])
            if u["type"] not in ("worker", "scout"):
                raise E.GameError("Автоматизировать можно рабочих и разведчиков")
            u["auto"] = not u.get("auto")
            toast = "🤖 Автоматический режим включён" if u["auto"] else "Автоматический режим выключен"
            if u["auto"] and not ai.auto_step(s, uid, a[1]):
                u["auto"] = False
                toast = "Пока нечего исследовать"
            save(chat, s)
            v = view_unit(s, uid, a[1])
        elif cmd == "x":
            toast = E.disband(s, uid, a[1])
            save(chat, s)
            v = view_units(s, uid)
        elif cmd == "cs":
            v = view_cities(s, uid)
        elif cmd == "c":
            v = view_city(s, uid, a[1])
        elif cmd == "bs":
            v = view_build(s, uid, a[1])
        elif cmd == "b":
            toast = E.set_build(s, uid, a[1], f"{a[2]}:{a[3]}")
            save(chat, s)
            v = view_city(s, uid, a[1])
        elif cmd == "by":
            toast = E.buy(s, uid, a[1])
            save(chat, s)
            v = view_city(s, uid, a[1])
        elif cmd == "ts":
            v = view_tech(s, uid)
        elif cmd == "t":
            toast = E.set_research(s, uid, a[1])
            save(chat, s)
            v = view_main(s, uid)
        elif cmd == "dp":
            v = view_diplo(s, uid)
        elif cmd in ("dw", "pp", "ap"):
            fn = {"dw": E.declare_war, "pp": E.propose_peace, "ap": E.accept_peace}[cmd]
            toast, public = fn(s, uid, a[1])
            save(chat, s)
            v = view_diplo(s, uid)
        elif cmd == "g":
            toast = E.cs_gift(s, uid, a[1])
            save(chat, s)
            v = view_diplo(s, uid)
        elif cmd == "gw":
            toast, public = E.cs_declare_war(s, uid, a[1])
            save(chat, s)
            v = view_diplo(s, uid)
        elif cmd == "gp":
            toast = E.cs_make_peace(s, uid, a[1])
            save(chat, s)
            v = view_diplo(s, uid)
        elif cmd == "img":
            await send_map(cb.message, s, uid)
            return await cb.answer()
        elif cmd == "end":
            if E.set_ready(s, uid):
                await run_turn(cb.bot, chat, s)
                toast = "Новый ход!"
            else:
                save(chat, s)
                toast = "Ход завершён. Ждём остальных."
            v = view_main(s, uid)
        else:
            return await cb.answer()
    except E.GameError as e:
        return await cb.answer(str(e), show_alert=True)
    if public:
        await cb.bot.send_message(chat, public)
    await show(cb, v)
    await cb.answer(toast)


async def main():
    logging.basicConfig(level=logging.INFO)
    bot = Bot(TOKEN)
    try:
        me = await bot.get_me()
        logging.info("Бот запущен: @%s. Напишите ему /start", me.username)
    except Exception as e:
        logging.error("Не удалось войти в Telegram (%s). Проверьте токен BOT_TOKEN и интернет.", e)
        raise SystemExit(1)
    dp = Dispatcher()
    dp.include_router(router)
    try:
        await bot.set_my_commands([
            BotCommand(command="menu", description="Игровое меню"),
            BotCommand(command="play", description="Открыть карту (Mini App)"),
            BotCommand(command="map", description="Карта картинкой"),
            BotCommand(command="newgame", description="Создать игру"),
            BotCommand(command="join", description="Вступить в игру"),
            BotCommand(command="addai", description="Добавить компьютерного игрока"),
            BotCommand(command="difficulty", description="Сложность ИИ"),
            BotCommand(command="hints", description="Подсказки вкл/выкл"),
            BotCommand(command="begin", description="Начать игру"),
            BotCommand(command="rules", description="Правила"),
            BotCommand(command="stats", description="Моя статистика"),
            BotCommand(command="top", description="Таблица лидеров"),
            BotCommand(command="history", description="Последние партии"),
            BotCommand(command="rollback", description="Откат хода (создатель)"),
            BotCommand(command="export", description="Сохранить игру файлом"),
            BotCommand(command="endgame", description="Удалить игру"),
        ])
    except Exception:
        logging.exception("Не удалось задать список команд")
    # Render Web Service needs an HTTP listener. The bot remains Telegram-first;
    # this page only reports that the service is alive.
    async def home(_request):
        return web.Response(
            text=("<html><head><meta charset='utf-8'><title>Цивилизация</title>"
                  "<meta name='viewport' content='width=device-width, initial-scale=1'>"
                  "<style>body{font:16px system-ui;max-width:680px;margin:12vh auto;padding:24px;"
                  "background:#101820;color:#f4f1de}main{padding:32px;border:1px solid #50616d;"
                  "border-radius:18px;background:#17232d}h1{color:#e9c46a}a{color:#80ed99}</style>"
                  "</head><body><main><h1>Цивилизация работает</h1>"
                  "<p>Сервер запущен. Чтобы играть, откройте бота в Telegram и отправьте "
                  "<code>/start</code>.</p><p><a href='/health'>Проверка состояния</a></p>"
                  "</main></body></html>"),
            content_type="text/html",
        )

    async def health(_request):
        return web.json_response({"status": "ok", "telegram_bot": "running"})

    app = web.Application()
    app.router.add_get("/", home)
    app.router.add_get("/health", health)
    webapi.setup(app, token=TOKEN, load=load, save=save, run_turn=run_turn, bot=bot)   # Mini App: /app, /api/*
    runner = web.AppRunner(app)
    await runner.setup()
    port = int(os.getenv("PORT", "10000"))
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
    logging.info("HTTP status page listening on 0.0.0.0:%s", port)

    task = asyncio.create_task(ticker(bot))   # таймер смены хода
    try:
        await dp.start_polling(bot)
    finally:
        task.cancel()
        await runner.cleanup()


if __name__ == "__main__":
    asyncio.run(main())
