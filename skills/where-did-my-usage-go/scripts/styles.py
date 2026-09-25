"""The terminal and receipt card styles. Classic lives in render_png.py.

Both reuse the same view model and drawing helpers, so visibility rules and
the privacy scan apply exactly as they do to the classic card.
"""

import random
from datetime import datetime, timedelta
from functools import lru_cache

from PIL import Image, ImageChops, ImageDraw, ImageFilter

import render_png as R
from card import REPO_LABEL, busiest, compact, hour_label, number, price, view

SIZE = (1080, 1350)


@lru_cache(maxsize=None)
def _noise_tile():
    """Seeded, softened grain: the same report always renders the same bytes, and the
    blur keeps the PNG around 400KB instead of 1MB."""
    rng = random.Random(7)
    tile = Image.new("L", (256, 256))
    tile.putdata([rng.randint(88, 168) for _ in range(256 * 256)])
    return tile.filter(ImageFilter.GaussianBlur(2.5)).convert("RGB")


def grain(image, amount):
    noise = Image.new("RGB", image.size)
    for x in range(0, image.width, 256):
        for y in range(0, image.height, 256):
            noise.paste(_noise_tile(), (x, y))
    return Image.blend(image, ImageChops.overlay(image, noise), amount)


def backdrop(center, edge, spread):
    """A soft radial surface: `center` in the middle falling off to `edge`."""
    fade = Image.new("L", SIZE, 0)
    ImageDraw.Draw(fade).ellipse((-spread, -spread // 2, SIZE[0] + spread, SIZE[1] + spread // 2), fill=255)
    fade = fade.filter(ImageFilter.GaussianBlur(220))
    return Image.composite(Image.new("RGB", SIZE, center), Image.new("RGB", SIZE, edge), fade)


def drop_shadow(canvas, mask, offset, blur, opacity):
    layer = Image.new("L", canvas.size, 0)
    layer.paste(mask.point(lambda value: round(value * opacity)), offset)
    canvas.paste(Image.new("RGB", canvas.size, "#000000"), (0, 0), layer.filter(ImageFilter.GaussianBlur(blur)))


def window_flag(data):
    hours = data.get("window_hours")
    if not isinstance(hours, (int, float)) or hours <= 0:
        return ""
    return f" --last {round(hours / 24)}d" if hours >= 48 and round(hours) % 24 == 0 else f" --last {round(hours)}h"


def api_total(card):
    return price(card["api_usd"]) + ("+" if card["api_partial"] or card["api_floor"] else "") if card["api_usd"] is not None else None


def terminal(data, visibility):
    bg, ink, dim, green, amber = "#0c0e0c", "#d8e0d4", "#6b7568", "#7ee787", "#e3b341"
    R.C.clear()
    R.C.update(bg=bg, ink=ink, muted=dim, faint=dim, line="#242923", accent=green)
    card = view(data, visibility)
    image = Image.new("RGB", SIZE, "#050605")
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle((48, 48, 1032, 1302), radius=18, fill=bg, outline="#1f231e", width=2)
    for index, color in enumerate(("#ff5f57", "#febc2e", "#28c840")):
        draw.ellipse((80 + index * 30, 76, 96 + index * 30, 92), fill=color)
    title = "where-did-my-usage-go"
    R.text(draw, (540 - R.width(draw, title, R.font(18, "mono")) / 2, 90), title, R.font(18, "mono"), dim)
    mono, med = R.font(24, "mono"), R.font(24, "mono-medium")
    x, right, y = 90, 990, 170
    R.text(draw, (x, y), "$ ", med, green)
    R.text(draw, (x + 30, y), f"wdmug{window_flag(data)} --roast", med, ink)
    y += 60
    who = card["name"] + (f" @{card['handle']}" if card["handle"] else "")
    R.text(draw, (x, y), R.fit(draw, who, med, 560), med, ink)
    tier = f"[{'#' * card['tier_level']}{'.' * (5 - card['tier_level'])}] {card['tier_label'].lower()}"
    R.text(draw, (right, y), tier, mono, amber, anchor="rs")
    y += 120
    total = compact(card["total"]) if card["total"] is not None else "?"
    big = R.font(88, "mono-medium")
    R.text(draw, (x - 4, y), total, big, green)
    R.text(draw, (x + R.width(draw, total, big) + 12, y), "tokens", mono, dim)
    y += 56
    R.text(draw, (x, y), f"{api_total(card)} at api list prices" if card["api_usd"] is not None else "api price unavailable", med, ink)
    if card["trend"]:
        R.text(draw, (right, y), card["trend"], mono, dim, anchor="rs")
    y += 70

    def bar(y, label, share, suffix):
        R.text(draw, (x, y), R.fit(draw, label.lower(), mono, 230), mono, ink)
        cells = 30
        filled = round(cells * (share or 0) / 100)
        R.text(draw, (x + 250, y), "█" * filled + "░" * (cells - filled), mono, green if filled else dim)
        R.text(draw, (right, y), suffix, mono, dim, anchor="rs")

    R.text(draw, (x, y), "# tools", mono, dim)
    y += 42
    for row in card["agents"][:4]:
        bar(y, row["label"], row["share"], row["share_text"] or "n/a")
        y += 38
    y += 24
    R.text(draw, (x, y), "# projects", mono, dim)
    y += 42
    for row in card["projects"][:3]:
        bar(y, row["label"], row["share"], compact(row["tokens"]) if isinstance(row["tokens"], int) else "n/a")
        y += 38
    y += 24
    if card["hours"] and sum(card["hours"]) >= 10:
        R.text(draw, (x, y), "# prompts by hour", mono, dim)
        peak = max(range(24), key=lambda hour: card["hours"][hour])
        R.text(draw, (right, y), f"peak {hour_label(peak)}", mono, dim, anchor="rs")
        y += 22
        for hour, count in enumerate(card["hours"]):
            height = max(3, round(40 * count / card["hours"][peak]))
            bx = x + hour * 37.5
            draw.rectangle((bx, y + 40 - height, bx + 26, y + 40), fill=green if hour == peak else ("#3d6b42" if count else "#1d221c"))
        y += 90
    facts = []
    if card["limit"]:
        period = {300: "5h", 1440: "daily", 10080: "weekly"}.get(card["limit"]["window_minutes"], "plan")
        facts.append(f"{card['limit']['agent'].lower()} {period} limit: {card['limit']['used_percent']:.0f}%")
    if card["cache_share"] is not None:
        facts.append(f"cache reads: {card['cache_share']}%")
    facts.append(f"sessions: {number(card['sessions'])}")
    R.text(draw, (x, y), "   ".join(facts[:3]), mono, amber)
    y += 64
    for line in R.wrap(draw, "> " + card["roast"], R.font(28, "mono-medium"), 880, 3):
        R.text(draw, (x, y), line, R.font(28, "mono-medium"), ink)
        y += 40
    small = R.font(18, "mono")
    R.text(draw, (x, 1262), REPO_LABEL, small, dim)
    cursor = x + R.width(draw, REPO_LABEL, small) + 8
    draw.rectangle((cursor, 1246, cursor + 12, 1266), fill=green)
    # Float the window on a slate gradient, the way developers share code screenshots.
    window = image.crop((48, 48, 1033, 1303))
    mask = Image.new("L", window.size, 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, window.width - 1, window.height - 1), radius=18, fill=255)
    size = (round(window.width * 0.9), round(window.height * 0.9))
    window, mask = window.resize(size, Image.LANCZOS), mask.resize(size, Image.LANCZOS)
    canvas = backdrop("#51607f", "#1c2230", 300)
    x, y = (SIZE[0] - size[0]) // 2, (SIZE[1] - size[1]) // 2
    drop_shadow(canvas, mask, (x, y + 22), 34, 0.55)
    canvas.paste(window, (x, y), mask)
    return canvas


def receipt_summary(card):
    """The remaining stats as a few plain sentences instead of one row per number."""
    sentences = []
    if card["total"] is not None:
        sentences.append(f"{compact(card['total'])} tokens over {number(card['sessions'])} sessions"
                         + (f", {card['cache_share']}% of them cache reads." if card["cache_share"] is not None else "."))
    else:
        sentences.append(f"{number(card['sessions'])} sessions with no recorded tokens.")
    if card["limit"]:
        period = {300: "5-hour", 1440: "daily", 10080: "weekly"}.get(card["limit"]["window_minutes"], "plan")
        sentences.append(f"Used {card['limit']['used_percent']:.0f}% of the {period} {card['limit']['agent']} limit.")
    if card["trend"]:
        sentences.append(card["trend"].replace("previous", "the previous") + ".")
    return " ".join(sentences)


def receipt_items(data, card):
    """One row per tool, like the other styles, with its priciest models underneath."""
    by_agent = {}
    estimate = data.get("estimated_api_cost") if card["api_usd"] is not None else None
    for part in (estimate or {}).get("components", []):
        tokens = sum(part.get(key, 0) for key in ("noncached_input_tokens", "cached_input_tokens",
                                                   "cache_write_tokens", "cache_write_1h_tokens", "output_tokens"))
        models = by_agent.setdefault(part["agent"], {})
        previous = models.get(part["model"], (0, 0.0))
        models[part["model"]] = (previous[0] + tokens, previous[1] + part["usd"])
    rows = []
    for agent in card["agents"]:
        if agent["label"] == "Other tools":
            names = [name for name in by_agent if name not in {row["label"] for row in card["agents"]}]
            models = {model: value for name in names for model, value in by_agent[name].items()}
        else:
            models = by_agent.get(agent["label"], {})
        priced = sum(usd for _, usd in models.values())
        tokens = compact(agent["tokens"]) if isinstance(agent["tokens"], int) else "n/a"
        rows.append((agent["label"], tokens, f"{priced:,.2f}" if models else "--", False))
        ranked = sorted(models.items(), key=lambda item: -item[1][1])
        if len(ranked) > 1:
            rows += [(f"  {model}", compact(count), f"{usd:,.2f}", True) for model, (count, usd) in ranked[:2]]
            if len(ranked) > 2:
                rows.append((f"  +{len(ranked) - 2} more model{'s' if len(ranked) > 3 else ''}", "", "", True))
    return rows


def report_week(data):
    """The ISO week the report covers (its last full day), not the week it was exported."""
    try:
        end = datetime.fromisoformat(data["window_end"]) - timedelta(seconds=1)
    except (KeyError, TypeError, ValueError):
        end = datetime.now()
    return end.isocalendar().week


def receipt(data, visibility):
    ink, dim, rule_color, paper = "#1d1d1b", "#6f6d66", "#8c897f", "#f6f3ea"
    R.C.clear()
    R.C.update(bg=paper, ink=ink, muted=dim, faint=dim, line=rule_color, accent=ink)
    card = view(data, visibility)
    width, margin = 700, 40
    sheet = Image.new("RGB", (width, 2400), paper)
    draw = ImageDraw.Draw(sheet)
    left, right, center = margin, width - margin, width // 2
    mono, bold, small = R.font(20, "mono"), R.font(20, "mono-medium"), R.font(17, "mono")

    def centered(y, value, face=mono, fill=ink):
        R.text(draw, (center - R.width(draw, value, face) / 2, y), value, face, fill)

    def rule(y, char="-"):
        R.text(draw, (left, y), char * 50, mono, rule_color)

    def columns(y, cells, face=mono, fill=ink):
        label, middle, last = cells
        R.text(draw, (left, y), R.fit(draw, label, face, 330), face, fill)
        R.text(draw, (right - 150, y), middle, face, fill, anchor="rs")
        R.text(draw, (right, y), last, face, fill, anchor="rs")

    y = 70
    centered(y, "WHERE DID MY USAGE GO?", R.font(26, "mono-medium"))
    y += 38
    centered(y, card["window"].upper(), mono, dim)
    y += 26
    customer = card["name"].upper() + (f" (@{card['handle'].upper()})" if card["handle"] else "")
    centered(y, R.fit(draw, f"ORDER #{report_week(data):02d}  CUSTOMER {customer}", mono, right - left), mono, dim)
    y += 34
    rule(y)
    y += 36
    columns(y, ("TOOL", "TOKENS", "USD"), bold)
    y += 32
    for label, tokens, usd, detail in receipt_items(data, card):
        columns(y, (label, tokens, usd), small if detail else mono, dim if detail else ink)
        y += 26 if detail else 30
    y += 4
    rule(y)
    y += 36
    if card["projects"]:
        columns(y, ("WHERE IT WENT", "TOKENS", "SHARE"), bold)
        y += 32
        for row in card["projects"][:4]:
            columns(y, (row["label"], compact(row["tokens"]) if isinstance(row["tokens"], int) else "n/a",
                        row["share_text"] or "--"))
            y += 30
        y += 4
        rule(y)
        y += 36
    when = busiest(card)
    if when:
        R.text(draw, (left, y), "PEAK HOURS", bold, ink)
        y += 16
        counts, slot = card["hours"], (right - left) / 24
        for hour, count in enumerate(counts):
            height = max(2, round(44 * count / max(counts)))
            draw.rectangle((left + hour * slot + 2, y + 48 - height, left + (hour + 1) * slot - 3, y + 48), fill=ink if count else "#d8d3c6")
        for hour, label in ((0, "12am"), (6, "6am"), (12, "12pm"), (18, "6pm")):
            R.text(draw, (left + hour * slot + 2, y + 72), label, small, dim)
        y += 110
        R.text(draw, (left, y), f"Busiest: {when}.", mono, ink)
        y += 26
        rule(y)
        y += 38
    for line in R.wrap(draw, receipt_summary(card), mono, right - left, 5):
        R.text(draw, (left, y), line, mono, ink)
        y += 28
    y += 6
    rule(y, "=")
    y += 52
    total_face = R.font(34, "mono-medium")
    R.text(draw, (left, y), "TOTAL", total_face, ink)
    R.text(draw, (right, y), api_total(card) if card["api_usd"] is not None else f"{compact(card['total'])} TKN", total_face, ink, anchor="rs")
    y += 30
    note = "at API list prices. you paid a subscription." if card["api_usd"] is not None else "no verified API price for these models."
    R.text(draw, (left, y), note, mono, dim)
    y += 26
    rule(y, "=")
    y += 44
    for line in R.wrap(draw, card["roast"].upper(), bold, right - left, 3):
        centered(y, line, bold)
        y += 28
    y += 20
    centered(y, f"** {card['tier_label'].upper()} TIER **", R.font(24, "mono-medium"))
    y += 30
    for x in range(left + 80, right - 80, 7):  # barcode motif
        draw.rectangle((x, y, x + 1 + (x * 7919) % 4, y + 40), fill=ink)
    y += 70
    centered(y, REPO_LABEL, mono, dim)
    height = y + 44
    # Cut the paper out with a torn bottom edge, add grain, and lay it on a gray desk with a slight tilt.
    teeth = round(width / 20)
    paper_mask = Image.new("L", (width, height + 14), 0)
    mask_draw = ImageDraw.Draw(paper_mask)
    mask_draw.rectangle((0, 0, width, height), fill=255)
    for index in range(teeth):
        x = index * width / teeth
        mask_draw.polygon([(x, height), (x + width / teeth / 2, height + 14), (x + width / teeth, height)], fill=255)
    strip = grain(sheet.crop((0, 0, width, height + 14)), 0.25).convert("RGBA")
    strip.putalpha(paper_mask)
    strip = strip.rotate(-1.0, resample=Image.BICUBIC, expand=True)
    room = SIZE[1] - 90
    if strip.height > room:  # a long week shrinks the receipt rather than dropping lines
        strip = strip.resize((round(strip.width * room / strip.height), room), Image.LANCZOS)
    canvas = backdrop("#2a2b2e", "#111214", 300)
    x, top = (SIZE[0] - strip.width) // 2, (SIZE[1] - strip.height) // 2
    drop_shadow(canvas, strip.getchannel("A"), (x + 10, top + 22), 22, 0.6)
    canvas.paste(strip, (x, top), strip)
    return canvas
