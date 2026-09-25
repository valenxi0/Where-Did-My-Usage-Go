#!/usr/bin/env python3
"""Render a saved share report to a social-ready PNG without model calls."""

import argparse
import json
from functools import lru_cache
from pathlib import Path

try:
    from PIL import Image, ImageDraw, ImageFont
except ImportError as exc:
    raise SystemExit("PNG export needs Pillow. Install it once with `python3 -m pip install Pillow`.") from exc

from card import REPO_LABEL, TIERS, compact, hour_label, number, plural, price, stat_cells, view

SIZE = (1080, 1350)
LEFT, RIGHT = 72, 1008
STATS_TOP = 1116
ROW = 86
THEMES = {
    "night": {"bg": "#0e100c", "ink": "#eef1e6", "muted": "#8d957f", "faint": "#5c6456", "line": "#262b22", "accent": "#c6f36b"},
    "paper": {"bg": "#f3f4f1", "ink": "#121412", "muted": "#62675f", "faint": "#8b9087", "line": "#d9dbd4", "accent": "#2b4dff"},
    "ember": {"bg": "#121110", "ink": "#f2efeb", "muted": "#9a948d", "faint": "#67625d", "line": "#2a2724", "accent": "#ff6b2c"},
    "cobalt": {"bg": "#0b1020", "ink": "#eef1f8", "muted": "#8a93ab", "faint": "#5a6380", "line": "#1e2640", "accent": "#7aa2ff"},
}
DEFAULT_THEME = "paper"
C = dict(THEMES[DEFAULT_THEME])
FONTS = Path(__file__).resolve().parent.parent / "assets/fonts"
FACES = {"regular": "Geist-Regular.ttf", "medium": "Geist-Medium.ttf", "semibold": "Geist-SemiBold.ttf",
         "black": "Geist-Black.ttf", "mono": "GeistMono-Regular.ttf", "mono-medium": "GeistMono-Medium.ttf"}


@lru_cache(maxsize=None)
def font(size, face="regular"):
    try:
        return ImageFont.truetype(str(FONTS / FACES[face]), size)
    except OSError:
        return ImageFont.load_default(size=size)


def mix(color, amount):
    """Blend C["accent"]-family colors toward the background so segments stay one hue."""
    a = [int(color[i:i + 2], 16) for i in (1, 3, 5)]
    b = [int(C["bg"][i:i + 2], 16) for i in (1, 3, 5)]
    return "#" + "".join(f"{round(x * amount + y * (1 - amount)):02x}" for x, y in zip(a, b))


def width(draw, value, face, tracking=0):
    return draw.textlength(value, font=face) + tracking * max(0, len(value) - 1)


def text(draw, xy, value, face, fill, tracking=0, anchor="ls"):
    """Draw on a baseline anchor; negative tracking tightens display type."""
    x, y = xy
    if anchor[0] == "r":
        x -= width(draw, value, face, tracking)
    if not tracking:
        draw.text((x, y), value, font=face, fill=fill, anchor="l" + anchor[1])
        return
    for char in value:
        draw.text((x, y), char, font=face, fill=fill, anchor="l" + anchor[1])
        x += draw.textlength(char, font=face) + tracking


def fit(draw, value, face, max_width):
    value = str(value or "")
    if width(draw, value, face) <= max_width:
        return value
    while value and width(draw, value + "…", face) > max_width:
        value = value[:-1]
    return value.rstrip() + "…"


def wrap(draw, value, face, max_width, max_lines):
    words, lines, line = str(value or "").split(), [], ""
    for word in words:
        candidate = f"{line} {word}".strip()
        if width(draw, candidate, face) <= max_width:
            line = candidate
            continue
        if line:
            lines.append(line)
        line = word
        if len(lines) == max_lines:
            break
    if line and len(lines) < max_lines:
        lines.append(line)
    if " ".join(lines) != " ".join(words):
        lines[-1] = fit(draw, lines[-1] + "…", face, max_width)
    return lines


def header(draw, card):
    text(draw, (LEFT, 84), "where did my usage go", font(22, "mono-medium"), C["ink"])
    mark_x = LEFT + width(draw, "where did my usage go", font(22, "mono-medium"))
    text(draw, (mark_x, 84), "?", font(22, "mono-medium"), C["accent"])
    text(draw, (RIGHT, 84), fit(draw, card["window"], font(20, "mono"), 470), font(20, "mono"), C["muted"], anchor="rs")
    draw.line((LEFT, 112, RIGHT, 112), fill=C["line"], width=2)


def identity(draw, card):
    text(draw, (LEFT, 186), fit(draw, card["name"], font(54, "semibold"), 640), font(54, "semibold"), C["ink"], tracking=-1.5)
    if card["handle"]:
        text(draw, (LEFT, 226), f"@{card['handle']}", font(24, "mono"), C["muted"])
    size, gap, count = 20, 8, len(TIERS)
    for index in range(count):
        x = RIGHT - (count - index) * size - (count - 1 - index) * gap
        draw.rounded_rectangle((x, 150, x + size, 150 + size), radius=4,
                               fill=C["accent"] if index < card["tier_level"] else C["line"])
    text(draw, (RIGHT, 212), card["tier_label"].upper(), font(22, "mono-medium"),
         C["accent"] if card["tier_level"] else C["muted"], anchor="rs")


def hero(draw, card):
    value = compact(card["total"]) if card["total"] is not None else "?"
    size = 208
    unit_face = font(52, "medium")
    while width(draw, value, font(size, "black"), -size * 0.03) + 28 + width(draw, "tokens", unit_face) > RIGHT - LEFT:
        size -= 6
    face = font(size, "black")
    baseline = 280 + round(size * 0.72)
    text(draw, (LEFT - 6, baseline), value, face, C["ink"], tracking=-size * 0.03)
    unit_x = LEFT - 6 + width(draw, value, face, -size * 0.03) + 24
    text(draw, (unit_x, baseline), "tokens" if card["total"] is not None else "tokens unrecorded", unit_face, C["muted"])
    y = baseline + 104
    if card["api_usd"] is not None:
        amount_face = font(64, "semibold")
        amount = price(card["api_usd"]) + ("+" if card["api_partial"] or card["api_floor"] else "")
        text(draw, (LEFT, y), amount, amount_face, C["accent"], tracking=-1.5)
        text(draw, (LEFT + width(draw, amount, amount_face, -1.5) + 18, y), "at API list prices", font(22, "mono"), C["muted"])
    if card["trend"]:
        text(draw, (RIGHT, y), card["trend"], font(22, "mono-medium"), C["ink"], anchor="rs")
    return y if card["api_usd"] is not None or card["trend"] else baseline + 12


def roast(draw, card, top):
    # Prefer two lines: shrink the type before spending a third line of the card on it.
    for size in (42, 38, 35):
        face = font(size, "medium")
        lines = wrap(draw, card["roast"], face, RIGHT - LEFT - 34, 3)
        if len(lines) <= 2:
            break
    step = round(size * 1.24)
    draw.rectangle((LEFT, top, LEFT + 5, top + 16 + len(lines) * step), fill=C["accent"])
    for index, line in enumerate(lines):
        text(draw, (LEFT + 34, top + 44 + index * step), line, face, C["ink"], tracking=-0.6)
    return top + 16 + len(lines) * step


def tools(draw, card, top):
    measured = [row for row in card["agents"] if row["share"]]
    shades = [1, 0.62, 0.4, 0.24]
    bar_top, bar_bottom, gap = top, top + 18, 5
    x = LEFT
    available = RIGHT - LEFT - gap * max(0, len(measured) - 1)
    for index, row in enumerate(measured):
        end = RIGHT if index == len(measured) - 1 else x + max(10, round(available * row["share"] / 100))
        draw.rounded_rectangle((x, bar_top, end, bar_bottom), radius=4, fill=mix(C["accent"], shades[min(index, 3)]))
        x = end + gap
    if not measured:
        draw.rounded_rectangle((LEFT, bar_top, RIGHT, bar_bottom), radius=4, outline=C["line"], width=2)
    x = LEFT
    label_face, metric_face = font(22, "medium"), font(20, "mono")
    for index, row in enumerate(card["agents"][:4]):
        metric = row["share_text"] or "no token data"
        label = fit(draw, row["label"], label_face, 200)
        item_width = 22 + width(draw, label, label_face) + 12 + width(draw, metric, metric_face)
        if x + item_width > RIGHT:
            break
        swatch = mix(C["accent"], shades[min(measured.index(row), 3)]) if row in measured else C["line"]
        draw.rounded_rectangle((x, top + 42, x + 12, top + 54), radius=3, fill=swatch)
        text(draw, (x + 22, top + 55), label, label_face, C["ink"])
        text(draw, (x + 22 + width(draw, label, label_face) + 12, top + 55), metric, metric_face, C["muted"])
        x += item_width + 34
    return top + 55


def projects(draw, card, top, rows):
    text(draw, (LEFT, top + 22), "Where it went", font(24, "semibold"), C["ink"])
    y = top + 42
    for row in card["projects"][:rows]:
        draw.line((LEFT, y, RIGHT, y), fill=C["line"], width=1)
        metric = row["share_text"] or "n/a"
        metric_face = font(30, "mono-medium")
        text(draw, (RIGHT, y + 44), metric, metric_face, C["accent"] if row["share"] is not None else C["muted"], anchor="rs")
        name_face = font(30, "semibold")
        text(draw, (LEFT, y + 44), fit(draw, row["label"], name_face, 700), name_face, C["ink"], tracking=-0.4)
        amount = f"{compact(row['tokens'])} tokens" if isinstance(row["tokens"], int) else plural(row["sessions"], "session")
        text(draw, (RIGHT, y + 74), amount, font(20, "mono"), C["muted"], anchor="rs")
        detail = row["summary"] or plural(row["sessions"], "session")
        text(draw, (LEFT, y + 74), fit(draw, detail, font(22), RIGHT - LEFT - width(draw, amount, font(20, "mono")) - 32),
             font(22), C["muted"])
        y += ROW
    return y


def stats(draw, card, top):
    cells = stat_cells(card)
    draw.line((LEFT, top, RIGHT, top), fill=C["line"], width=2)
    cell = (RIGHT - LEFT) / len(cells)
    for index, (label, value) in enumerate(cells):
        x = LEFT + index * cell + (0 if index == 0 else 28)
        if index:
            draw.line((LEFT + index * cell, top + 24, LEFT + index * cell, top + 104), fill=C["line"], width=2)
        text(draw, (x, top + 50), label, font(19, "mono"), C["muted"])
        text(draw, (x, top + 98), fit(draw, value, font(40, "semibold"), cell - 40), font(40, "semibold"), C["ink"], tracking=-1)
    return top + 124


def hour_strip(draw, card, top):
    """Prompts per local hour: when the human, not the agent, was at the keyboard."""
    counts = card["hours"]
    peak = max(range(24), key=lambda hour: counts[hour])
    text(draw, (LEFT, top + 34), "busiest hour", font(19, "mono"), C["muted"])
    text(draw, (LEFT + 150, top + 34), hour_label(peak), font(19, "mono-medium"), C["ink"])
    x0, gap, height = LEFT + 250, 4, 34
    bar = (RIGHT - x0 - gap * 23) / 24
    for hour, count in enumerate(counts):
        x = x0 + hour * (bar + gap)
        size = max(3, round(height * count / counts[peak]))
        fill = C["accent"] if hour == peak else (mix(C["accent"], 0.45) if count else C["line"])
        draw.rounded_rectangle((x, top + 40 - size, x + bar, top + 40), radius=2, fill=fill)


def footer(draw, card, bottom=1350):
    for index, note in enumerate(card["notes"][:2]):
        text(draw, (LEFT, bottom - 80 + index * 22), fit(draw, note, font(15, "mono"), RIGHT - LEFT), font(15, "mono"), C["faint"])
    text(draw, (LEFT, bottom - 32), REPO_LABEL, font(18, "mono-medium"), C["accent"])


FORMATS = {"post": (1080, 1350), "story": (1080, 1920), "og": (1200, 630)}


STYLES = ("classic", "terminal", "receipt")


def render(data, visibility, theme=DEFAULT_THEME, fmt="post", style="classic"):
    """`post` is the 4:5 feed card; `story` centers it in the 9:16 safe zone; `og` is a link preview.

    `theme` colors the classic style; terminal and receipt have fixed palettes. Every
    style shares the same link preview, since it must stay legible at thumbnail size.
    """
    if fmt == "og":
        return render_og(data, visibility, theme)
    if fmt == "story":
        post = render(data, visibility, theme, style=style)
        image = Image.new("RGB", FORMATS["story"], post.getpixel((0, 0)))
        image.paste(post, (0, (FORMATS["story"][1] - post.height) // 2))
        return image
    if style != "classic":
        import styles  # imported here because styles.py builds on this module's helpers
        return getattr(styles, style)(data, visibility)
    C.clear()
    C.update(THEMES[theme])
    card = view(data, visibility)
    image = Image.new("RGB", SIZE, C["bg"])
    draw = ImageDraw.Draw(image)
    header(draw, card)
    identity(draw, card)
    y = roast(draw, card, hero(draw, card) + 36)
    y = tools(draw, card, y + 40)
    strip = card["hours"] is not None and sum(card["hours"]) >= 10
    limit = STATS_TOP - (56 if strip else 0)
    projects(draw, card, y + 40, rows=max(1, (limit - 4 - (y + 40 + 42)) // ROW))
    if strip:
        hour_strip(draw, card, limit - 6)
    stats(draw, card, STATS_TOP)
    footer(draw, card)
    return image


def render_og(data, visibility, theme):
    """1200x630 preview for GitHub and X links: identity, total, price, roast."""
    C.clear()
    C.update(THEMES[theme])
    card = view(data, visibility)
    image = Image.new("RGB", FORMATS["og"], C["bg"])
    draw = ImageDraw.Draw(image)
    left, right = 64, 1136
    text(draw, (left, 78), "where did my usage go", font(22, "mono-medium"), C["ink"])
    text(draw, (left + width(draw, "where did my usage go", font(22, "mono-medium")), 78), "?", font(22, "mono-medium"), C["accent"])
    text(draw, (right, 78), fit(draw, card["window"], font(20, "mono"), 520), font(20, "mono"), C["muted"], anchor="rs")
    text(draw, (left, 150), fit(draw, card["name"], font(40, "semibold"), 520), font(40, "semibold"), C["ink"], tracking=-1)
    value = compact(card["total"]) if card["total"] is not None else "?"
    size = 150
    text(draw, (left - 4, 330), value, font(size, "black"), C["ink"], tracking=-size * 0.03)
    text(draw, (left + width(draw, value, font(size, "black"), -size * 0.03) + 16, 330), "tokens", font(40, "medium"), C["muted"])
    if card["api_usd"] is not None:
        amount = price(card["api_usd"]) + ("+" if card["api_partial"] or card["api_floor"] else "")
        text(draw, (left, 420), amount, font(54, "semibold"), C["accent"], tracking=-1.2)
        text(draw, (left + width(draw, amount, font(54, "semibold"), -1.2) + 16, 420), "at API list prices", font(20, "mono"), C["muted"])
    lines = wrap(draw, card["roast"], font(30, "medium"), 470, 5)
    top = 315 - len(lines) * 19
    draw.rectangle((650, top - 34, 654, top - 34 + len(lines) * 38 + 10), fill=C["accent"])
    for index, line in enumerate(lines):
        text(draw, (676, top + index * 38), line, font(30, "medium"), C["ink"])
    text(draw, (left, 574), REPO_LABEL, font(18, "mono-medium"), C["accent"])
    return image


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--visibility", choices=("named", "anonymous", "private-projects"), required=True)
    parser.add_argument("--theme", choices=sorted(THEMES), default=DEFAULT_THEME)
    parser.add_argument("--format", choices=sorted(FORMATS), default="post")
    parser.add_argument("--style", choices=STYLES, default="classic")
    args = parser.parse_args()
    data = json.loads(args.input.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        parser.error("Input must be a JSON object")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    render(data, args.visibility, args.theme, args.format, args.style).save(args.output, format="PNG", optimize=True)
    args.output.chmod(0o600)
    print(f"Wrote {args.output}")


if __name__ == "__main__":
    main()
