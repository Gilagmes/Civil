"""Карта картинкой (PNG). Нужна библиотека Pillow; без неё render_png() вернёт None,
и бот покажет карту эмодзи."""
import io
import os

try:
    from PIL import Image, ImageDraw, ImageFont
except ImportError:      # Pillow не установлен
    Image = None

import engine as E

CELL = 46
MARGIN = 24
PLAYER_COLORS = [(214, 48, 49), (9, 132, 227), (0, 184, 148), (240, 190, 60), (140, 110, 230), (240, 140, 20)]
TERRAIN_COLORS = {"plains": (164, 204, 104), "forest": (86, 148, 82), "hills": (176, 146, 96), "water": (76, 146, 214)}
FONT_PATHS = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/TTF/DejaVuSans.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
    "/Library/Fonts/Arial Unicode.ttf",
    "/System/Library/Fonts/Supplemental/Arial.ttf",
    "C:/Windows/Fonts/arial.ttf",
]


def _font(size):
    for p in FONT_PATHS:
        if os.path.exists(p):
            try:
                return ImageFont.truetype(p, size), True
            except OSError:
                pass
    return ImageFont.load_default(), False     # без кириллицы


def _text(d, xy, text, font, fill, outline=None):
    x, y = xy
    if outline:
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                d.text((x + dx, y + dy), text, font=font, fill=outline)
    d.text((x, y), text, font=font, fill=fill)


def render_png(s, viewer, hl=None):
    """PNG-карта глазами игрока viewer (с туманом войны). None, если нет Pillow."""
    if Image is None:
        return None
    W, H = E.W, E.H
    vis = E.visible(s, viewer)
    seen = s["players"][viewer]["seen"]
    owners = E.tile_owners(s)
    small, _ = _font(11)
    label, label_ok = _font(12)

    def player_of(x, y):
        cid = owners.get((x, y))
        return s["cities"][cid]["owner"] if cid else None

    img = Image.new("RGB", (MARGIN + W * CELL, MARGIN + H * CELL), (24, 24, 30))   # RGB, чтобы полупрозрачность смешивалась
    d = ImageDraw.Draw(img, "RGBA")

    for x in range(W):
        _text(d, (MARGIN + x * CELL + CELL // 2 - 4, 6), str(x), small, (220, 220, 220))
    for y in range(H):
        _text(d, (6, MARGIN + y * CELL + CELL // 2 - 6), str(y), small, (220, 220, 220))

    for y in range(H):
        for x in range(W):
            x0, y0 = MARGIN + x * CELL, MARGIN + y * CELL
            x1, y1 = x0 + CELL, y0 + CELL
            if not seen[y * W + x]:
                d.rectangle([x0, y0, x1, y1], fill=(34, 34, 42), outline=(24, 24, 30))
                continue
            terr = s["map"][y][x]
            d.rectangle([x0, y0, x1, y1], fill=TERRAIN_COLORS[terr], outline=(40, 60, 40, 90))
            if terr == "forest":
                for ox, oy in ((10, 30), (22, 22), (32, 32)):
                    d.polygon([(x0 + ox, y0 + oy), (x0 + ox + 8, y0 + oy), (x0 + ox + 4, y0 + oy - 14)],
                              fill=(40, 100, 50))
            elif terr == "hills":
                d.polygon([(x0 + 4, y0 + 34), (x0 + 20, y0 + 12), (x0 + 34, y0 + 34)], fill=(140, 108, 66))
                d.polygon([(x0 + 22, y0 + 34), (x0 + 34, y0 + 20), (x0 + 44, y0 + 34)], fill=(120, 92, 56))
            elif terr == "water":
                for oy in (14, 28):
                    d.arc([x0 + 6, y0 + oy, x0 + 22, y0 + oy + 8], 200, 340, fill=(200, 230, 255), width=2)
                    d.arc([x0 + 24, y0 + oy, x0 + 40, y0 + oy + 8], 200, 340, fill=(200, 230, 255), width=2)
            im = s["impr"].get(f"{x},{y}")
            if im == "farm":
                for oy in (28, 34, 40):
                    d.line([(x0 + 8, y0 + oy), (x0 + 38, y0 + oy)], fill=(240, 210, 70), width=2)
            elif im == "mine":
                d.polygon([(x0 + 23, y0 + 8), (x0 + 34, y0 + 20), (x0 + 23, y0 + 32), (x0 + 12, y0 + 20)],
                          fill=(70, 70, 76))
            rs = s.get("res", {}).get(f"{x},{y}")
            if rs == "horses":
                d.ellipse([x0 + 26, y0 + 8, x0 + 40, y0 + 20], fill=(120, 70, 30), outline=(255, 255, 255))
            elif rs == "iron":
                d.rectangle([x0 + 28, y0 + 8, x0 + 40, y0 + 18], fill=(150, 160, 175), outline=(50, 55, 65), width=2)
            elif rs == "gems":
                d.polygon([(x0 + 34, y0 + 6), (x0 + 42, y0 + 14), (x0 + 34, y0 + 24), (x0 + 26, y0 + 14)],
                          fill=(120, 230, 255), outline=(255, 255, 255))
            if f"{x},{y}" in s.get("roads", []):
                d.line([(x0 + 2, y0 + CELL // 2), (x1 - 2, y0 + CELL // 2)], fill=(105, 78, 50), width=4)
            if f"{x},{y}" in s.get("huts", []):
                d.polygon([(x0 + 12, y0 + 34), (x0 + 12, y0 + 22), (x0 + 23, y0 + 12),
                           (x0 + 34, y0 + 22), (x0 + 34, y0 + 34)], fill=(120, 80, 50))
            wn = s.get("nwonders", {}).get(f"{x},{y}")
            if wn:
                d.polygon([(x0 + 23, y0 + 6), (x0 + 40, y0 + 23), (x0 + 23, y0 + 40), (x0 + 6, y0 + 23)],
                          fill=(255, 220, 120), outline=(255, 255, 255), width=2)
            if f"{x},{y}" in s.get("camps", []):
                d.polygon([(x0 + 10, y0 + 34), (x0 + 23, y0 + 14), (x0 + 36, y0 + 34)],
                          fill=(40, 40, 44), outline=(230, 60, 60), width=2)
                d.line([(x0 + 23, y0 + 14), (x0 + 23, y0 + 6)], fill=(230, 60, 60), width=2)
                d.polygon([(x0 + 23, y0 + 6), (x0 + 31, y0 + 9), (x0 + 23, y0 + 12)], fill=(230, 60, 60))
            po = player_of(x, y)
            if po is not None:
                col = PLAYER_COLORS[s["players"][po]["color"]]
                d.rectangle([x0, y0, x1, y1], fill=col + (55,))
                for nx, ny, edge in ((x, y - 1, [x0, y0, x1, y0]), (x, y + 1, [x0, y1, x1, y1]),
                                     (x - 1, y, [x0, y0, x0, y1]), (x + 1, y, [x1, y0, x1, y1])):
                    if not (0 <= nx < W and 0 <= ny < H) or player_of(nx, ny) != po:
                        d.line(edge, fill=col + (255,), width=3)
            if (x, y) not in vis:
                d.rectangle([x0, y0, x1, y1], fill=(0, 0, 0, 95))

    def castle(x0, y0, fill, outline=(255, 255, 255)):
        d.rectangle([x0 + 8, y0 + 16, x0 + 38, y0 + 38], fill=fill, outline=outline, width=2)
        for tx in (8, 20, 32):
            d.rectangle([x0 + tx, y0 + 9, x0 + tx + 6, y0 + 16], fill=fill, outline=outline)
        d.rectangle([x0 + 19, y0 + 26, x0 + 27, y0 + 38], fill=(40, 30, 30))

    for cid, c in s.get("cstates", {}).items():
        x, y = c["x"], c["y"]
        if seen[y * W + x]:
            x0, y0 = MARGIN + x * CELL, MARGIN + y * CELL
            castle(x0, y0, (150, 90, 190), (250, 220, 120))
            if label_ok:
                _text(d, (x0 + 1, y0 + CELL - 13), c["name"][:9], small, (255, 255, 255), (60, 30, 80))

    for cid, c in s["cities"].items():
        x, y = c["x"], c["y"]
        if (x, y) in vis:
            x0, y0 = MARGIN + x * CELL, MARGIN + y * CELL
            castle(x0, y0, PLAYER_COLORS[s["players"][c["owner"]]["color"]])
            if c["capital"]:
                d.polygon([(x0 + 23, y0 - 1), (x0 + 26, y0 + 6), (x0 + 33, y0 + 6), (x0 + 27, y0 + 10),
                           (x0 + 29, y0 + 17), (x0 + 23, y0 + 13), (x0 + 17, y0 + 17), (x0 + 19, y0 + 10),
                           (x0 + 13, y0 + 6), (x0 + 20, y0 + 6)], fill=(255, 220, 60))
            if label_ok:
                _text(d, (x0 + 1, y0 + CELL - 13), c["name"][:9], small, (255, 255, 255), (20, 20, 20))

    for y in range(H):
        for x in range(W):
            if (x, y) not in vis:
                continue
            us = E.units_at(s, x, y)
            if not us:
                continue
            boats = [v for _, v in us if E.UNITS[v["type"]].get("naval")]
            u = boats[0] if boats else us[0][1]
            cx, cy = MARGIN + x * CELL + CELL - 14, MARGIN + y * CELL + 14
            if boats:
                col = PLAYER_COLORS[s["players"][u["owner"]]["color"]]
                d.polygon([(cx - 13, cy + 3), (cx + 13, cy + 3), (cx + 8, cy + 11), (cx - 8, cy + 11)],
                          fill=(90, 60, 40), outline=(255, 255, 255))
                d.polygon([(cx, cy - 12), (cx + 10, cy + 1), (cx, cy + 1)], fill=col, outline=(255, 255, 255))
                if len(us) > 1:
                    _text(d, (cx - 20, cy - 8), "+" + str(len(us) - 1), small, (255, 255, 255), (0, 0, 0))
                continue
            if u["owner"] == "barb":
                d.ellipse([cx - 10, cy - 10, cx + 10, cy + 10], fill=(20, 20, 20), outline=(255, 255, 255), width=2)
                d.line([(cx - 5, cy - 5), (cx + 5, cy + 5)], fill=(230, 50, 50), width=3)
                d.line([(cx - 5, cy + 5), (cx + 5, cy - 5)], fill=(230, 50, 50), width=3)
            else:
                col = PLAYER_COLORS[s["players"][u["owner"]]["color"]]
                d.ellipse([cx - 10, cy - 10, cx + 10, cy + 10], fill=col, outline=(255, 255, 255), width=2)
                if E.UNITS[u["type"]]["att"] > 0:
                    d.line([(cx - 5, cy - 5), (cx + 5, cy + 5)], fill=(255, 255, 255), width=2)
                    d.line([(cx - 5, cy + 5), (cx + 5, cy - 5)], fill=(255, 255, 255), width=2)
                else:
                    d.rectangle([cx - 4, cy - 4, cx + 4, cy + 4], fill=(255, 255, 255))
            if len(us) > 1:
                _text(d, (cx - 18, cy - 8), str(len(us)), small, (255, 255, 255), (0, 0, 0))

    if hl:
        x0, y0 = MARGIN + hl[0] * CELL, MARGIN + hl[1] * CELL
        d.rectangle([x0 + 1, y0 + 1, x0 + CELL - 1, y0 + CELL - 1], outline=(255, 235, 60), width=4)

    out = io.BytesIO()
    img.save(out, "PNG")
    return out.getvalue()
