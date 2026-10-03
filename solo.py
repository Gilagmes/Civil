"""Одиночная игра в браузере без Telegram: человек против ИИ.

Запуск: python solo.py   (порт — переменная PORT, по умолчанию 8080)
Партия сохраняется в solo_save.json рядом с файлом.
"""
import asyncio
import json
import logging
import os

from aiohttp import web

import ai
import engine as E
import webapi

SAVE = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                    os.getenv("SOLO_SAVE", "solo_save.json"))


def load(_chat):
    if not os.path.exists(SAVE):
        return None
    try:
        s = json.load(open(SAVE, encoding="utf-8"))
        return s if s.get("ver") == E.VER else None
    except Exception:
        return None


def save(_chat, s):
    tmp = SAVE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(s, f, ensure_ascii=False)
    os.replace(tmp, SAVE)


async def run_turn(_bot, _chat, s):
    pub = E.process_turn(s)
    if not s["winner"]:
        pub += ai.play_all(s)
    s["pub"] = pub
    save("solo", s)


async def main():
    logging.basicConfig(level=logging.INFO)
    app = web.Application()

    async def health(_request):
        return web.json_response({"status": "ok", "mode": "solo"})

    app.router.add_get("/health", health)
    webapi.setup(app, token="", load=load, save=save, run_turn=run_turn, solo=True)
    runner = web.AppRunner(app)
    await runner.setup()
    port = int(os.getenv("PORT", "8080"))
    await web.TCPSite(runner, "0.0.0.0", port).start()
    logging.info("Solo mode listening on 0.0.0.0:%s", port)
    await asyncio.Event().wait()


if __name__ == "__main__":
    asyncio.run(main())
