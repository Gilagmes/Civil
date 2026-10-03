"""Подсказки для новичков: короткие советы по текущему состоянию игрока."""
import engine as E


def hints(s, uid, limit=2):
    p = s["players"][uid]
    cities = [(cid, c) for cid, c in s["cities"].items() if c["owner"] == uid]
    units = [(i, u) for i, u in s["units"].items() if u["owner"] == uid]
    out = []

    if not cities and any(u["type"] == "settler" for _, u in units):
        out.append("🏙 У вас ещё нет города: «Юниты» → Поселенец → «Основать город».")

    idle = [c for _, c in cities if not c["build"]]
    if idle:
        out.append(f"🔨 В городе {idle[0]['name']} ничего не строится: «Города» → город → «Что строить».")

    if not p["research"] and E.available_techs(s, uid):
        out.append("🔬 Не выбрана технология — наука пропадает впустую. Откройте «Наука».")

    mil = [u for _, u in units if E.UNITS[u["type"]]["att"] > 0 and not E.UNITS[u["type"]].get("naval")]
    barbs = any(u["owner"] == "barb" for u in s["units"].values())
    for _, c in cities:
        if not any((u["x"], u["y"]) == (c["x"], c["y"]) for u in mil) and (s["turn"] >= 5 or barbs):
            out.append(f"🛡 В городе {c['name']} нет защитника: его могут разграбить варвары. Постройте воина.")
            break

    techs = p["techs"]
    if any(u["type"] == "worker" and not u["job"] and not u.get("auto") and u["mv"] > 0 for _, u in units) \
            and ("agriculture" in techs or "mining" in techs):
        out.append("🧑‍🌾 Рабочий без дела: включите «🤖 Автоматически» в его меню.")

    if p["gold"] >= 40 and any(E.buy_price(s, c) for _, c in cities):
        out.append(f"💰 У вас {p['gold']} золота: в городе можно докупить производство («Города»).")

    if s["turn"] <= 12 and cities and not any(u["type"] == "scout" for _, u in units) \
            and not any(c["build"] == "unit:scout" for _, c in cities):
        out.append("🧭 Постройте разведчика: он откроет карту, селения 🛖 и города-государства 🏯.")

    if len(cities) == 1 and s["turn"] >= 6 and not any(u["type"] == "settler" for _, u in units) \
            and not any(c["build"] == "unit:settler" for _, c in cities):
        out.append("🌱 Больше городов — сильнее цивилизация: постройте Поселенца (нужно население 2).")

    for _, c in cities:
        lvl = E.city_level(c)
        if lvl < len(E.CITY_LEVELS):
            need = E.CITY_LEVELS[lvl][0]
            if c["pop"] == need - 1 and not p.get("_lvl_tip"):
                out.append(f"🎉 {c['name']} почти станет «{E.CITY_LEVELS[lvl][1]}» (население {need}) — это даёт бонусы.")
                break

    if E.can_found_religion(s, uid):
        out.insert(0, "🕊 Накоплено достаточно веры! Основайте религию: «🕊 Религия» в меню.")
    elif not p.get("religion") and cities and not any("temple" in c["buildings"] for _, c in cities) \
            and "writing" in techs and s["turn"] >= 8:
        out.append("🛐 Храм даёт культуру и веру: накопите веру и основайте свою религию.")

    if "wheel" in techs:
        lone = next((c for _, c in cities if not c["capital"] and not E.road_connected(s, c)), None)
        if lone and any(c["capital"] for _, c in cities):
            out.append(f"🛤 Соедините {lone['name']} дорогой со столицей: +{E.ROAD_LINK_GOLD}💰 за ход "
                       "(рабочий → «Построить дорогу» или «🤖 Автоматически»).")

    if p.get("religion") and s["turn"] >= 8 and not any(u["type"] == "missionary" for _, u in units) \
            and not any(c["build"] == "unit:missionary" for _, c in cities) \
            and any(c.get("religion") != p["religion"] for c in s["cities"].values()):
        out.append("📿 Постройте миссионера: он обратит соседний город в вашу веру "
                   "(религия в ≥60% городов 3 хода подряд — победа).")

    if not out and not p["ready"]:
        out.append("✅ Всё сделано? Нажмите «Завершить ход» — так игра идёт быстрее.")
    return out[:limit]
