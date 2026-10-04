"""Валидатор проекта: python tools/validate.py
1) компиляция всех .py; 2) синтаксис встроенного JS (нужен node, иначе пропуск);
3) симуляция партий ИИ с проверкой инвариантов; 4) served-preview: запуск solo.py на свободном порту
и прогон test_solo.py по HTTP; 5) совпадение версии в README и engine.GAME_VERSION.
"""
import collections
import os
import py_compile
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
FAILS = []


def step(name, ok, info=""):
    print(("✅ " if ok else "❌ ") + name + (f" — {info}" if info else ""))
    if not ok:
        FAILS.append(name)


def check_compile():
    bad = []
    for f in sorted(os.listdir(ROOT)):
        if f.endswith(".py"):
            try:
                py_compile.compile(os.path.join(ROOT, f), doraise=True)
            except py_compile.PyCompileError as e:
                bad.append(str(e))
    step("компиляция .py", not bad, "; ".join(bad))


def check_js():
    node = shutil.which("node")
    if not node:
        print("⏭  JS-синтаксис пропущен (нет node)")
        return
    html = open(os.path.join(ROOT, "web", "index.html"), encoding="utf-8").read()
    scripts = re.findall(r"<script(?![^>]*src)[^>]*>(.*?)</script>", html, re.S)
    bad = []
    for i, code in enumerate(scripts):
        tmp = os.path.join(tempfile.gettempdir(), f"civ_inline_{i}.js")
        open(tmp, "w", encoding="utf-8").write(code)
        r = subprocess.run([node, "--check", tmp], capture_output=True, text=True)
        if r.returncode:
            bad.append(r.stderr.strip()[:300])
    step(f"JS-синтаксис ({len(scripts)} блок.)", not bad, "; ".join(bad))


def check_version():
    import engine as E
    readme = open(os.path.join(ROOT, "README.md"), encoding="utf-8").read()
    step(f"версия README == {E.GAME_VERSION}", f"**v{E.GAME_VERSION}**" in readme)


def invariants(s):
    errs = []
    W, H = len(s["map"][0]), len(s["map"])
    if any(len(p["seen"]) != W * H for p in s["players"].values()):
        errs.append("размер seen не равен W*H")
    for uid, u in s["units"].items():
        if not (0 <= u["x"] < W and 0 <= u["y"] < H):
            errs.append(f"юнит {uid} вне карты")
        elif s["map"][u["y"]][u["x"]] == "water" and not u.get("aboard") \
                and u["type"] not in ("galley",):
            errs.append(f"юнит {uid} {u['type']} на воде")
        if u["owner"] not in s["players"] and u["owner"] != "barb":
            errs.append(f"юнит {uid} без владельца")
    for cid, c in s["cities"].items():
        if c["pop"] < 1:
            errs.append(f"город {cid} pop<1")
        if c["owner"] not in s["players"]:
            errs.append(f"город {cid} без владельца")
    pos = collections.Counter((c["x"], c["y"]) for c in s["cities"].values())
    errs += [f"два города на {p}" for p, n in pos.items() if n > 1]
    return errs


def check_sim():
    import ai
    import engine as E
    errs, idle = [], 0
    first_seen = {}
    plan = [(sd, "small") for sd in range(1, 7)] + [(11, "standard"), (12, "standard"), (13, "large")]
    for seed, size in plan:
        s = E.new_game("me", seed=seed, size=size)
        E.add_player(s, "me", "T")
        for name in ai.AI_NAMES[:2]:
            E.add_ai(s, name)
        E.set_difficulty(s, "normal")
        E.start(s)
        ai.play_all(s)
        for _ in range(45):
            if s["winner"]:
                break
            for uid, u in list(s["units"].items()):
                if u["owner"] == "me" and u["type"] == "settler":
                    try:
                        E.found_city(s, "me", uid)
                    except E.GameError:
                        pass
            E.process_turn(s)
            ai.play_all(s)
            errs += [f"seed {seed} t{s['turn']}: {e}" for e in invariants(s)]
            for uid, u in s["units"].items():
                if u["type"] == "settler" and u["owner"] != "me" and not u.get("aboard"):
                    pos, n = first_seen.get((seed, uid), (None, 0))
                    n = n + 1 if pos == (u["x"], u["y"]) else 1
                    first_seen[(seed, uid)] = ((u["x"], u["y"]), n)
                    if n == 4:
                        idle += 1
    E.set_size(*E.MAP_SIZES["small"])
    step("симуляции ИИ (9 партий × 45 ходов, 3 размера карты)", not errs, "; ".join(errs[:3]))
    step("ИИ не копит поселенцев", idle <= 3, f"застрявших поселенцев (4+ хода на месте): {idle}")


def check_queue():
    import engine as E
    s = E.new_game("me", seed=3)
    E.add_player(s, "me", "T")
    E.start(s)
    sett = next(i for i, u in s["units"].items() if u["type"] == "settler")
    E.found_city(s, "me", sett)
    cid = next(iter(s["cities"]))
    E.queue_add(s, "me", cid, "unit:warrior")
    E.queue_add(s, "me", cid, "unit:worker")
    E.queue_add(s, "me", cid, "unit:scout")
    done = []
    for _ in range(60):
        E.process_turn(s)
        c = s["cities"][cid]
        done.append(c["build"])
        if not c["build"] and not c.get("queue"):
            break
    seq = [b for i, b in enumerate(done) if b and (i == 0 or done[i - 1] != b)]
    ok = [b for b in seq if b in ("unit:worker", "unit:scout")][:2] == ["unit:worker", "unit:scout"] \
        and not s["cities"][cid].get("queue")
    n = {t: sum(1 for u in s["units"].values() if u["type"] == t) for t in ("warrior", "worker", "scout")}
    step("очередь производства выполняется по порядку", ok and n["worker"] >= 2 and n["scout"] >= 1, str(n))
    try:
        for _ in range(E.QUEUE_MAX + 2):
            E.queue_add(s, "me", cid, "unit:warrior")
        step("лимит очереди", False)
    except E.GameError:
        step("лимит очереди", True)


def check_preview():
    with socket.socket() as sk:
        sk.bind(("127.0.0.1", 0))
        port = sk.getsockname()[1]
    tmp = tempfile.mkdtemp()
    save = os.path.join(tmp, "save.json")
    env = dict(os.environ, PORT=str(port), SOLO_SAVE=save)
    proc = subprocess.Popen([sys.executable, os.path.join(ROOT, "solo.py")], env=env,
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        for _ in range(40):
            try:
                urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=1)
                break
            except Exception:
                time.sleep(0.25)
        page = urllib.request.urlopen(f"http://127.0.0.1:{port}/app", timeout=5).read().decode()
        step("served-preview: /app отдаёт страницу", "<html" in page.lower() and len(page) > 20000)
        src = open(os.path.join(ROOT, "test_solo.py"), encoding="utf-8").read()
        src = src.replace("http://127.0.0.1:8080", f"http://127.0.0.1:{port}")
        t = os.path.join(tmp, "t.py")
        open(t, "w", encoding="utf-8").write(src)
        r = subprocess.run([sys.executable, t], env=env, capture_output=True, text=True, timeout=180)
        step("served-preview: test_solo.py", r.returncode == 0 and "ALL OK" in r.stdout,
             (r.stderr or r.stdout)[-300:] if r.returncode else "")
    finally:
        proc.terminate()
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    check_compile()
    check_js()
    check_version()
    check_sim()
    check_queue()
    check_preview()
    print("\nИТОГО:", "всё хорошо ✅" if not FAILS else "ОШИБКИ: " + ", ".join(FAILS))
    sys.exit(1 if FAILS else 0)
