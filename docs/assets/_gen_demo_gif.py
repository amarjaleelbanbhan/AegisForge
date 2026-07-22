"""One-off generator for docs/assets/demo-terminal.gif.

Not part of the package build. Renders an accurate animation of the *current*
`ward scan .` CLI — the human-readable findings table introduced with the Rich
redesign — with a cursor that follows the typed command naturally.

Run it (Pillow is only needed here, not at runtime):

    uv run --with pillow python docs/assets/_gen_demo_gif.py
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

SCALE = 2
W, H = 780 * SCALE, 360 * SCALE

# GitHub-dark palette, matching the CLI's semantic theme.
BG = "#0d1117"
TITLEBAR = "#161b22"
BORDER = "#30363d"
TITLE_TEXT = "#8b949e"
PROMPT = "#58a6ff"  # accent / prompt
FG = "#e6edf3"
DIM = "#8b949e"  # muted
CRIT = "#ff7b72"  # bright red (CRITICAL)
HIGH = "#f85149"  # red (HIGH)
MED = "#d29922"  # yellow (MEDIUM)
GREEN = "#3fb950"  # success
CYAN = "#39c5cf"  # location / info


def _font(paths: list[str], size: int) -> ImageFont.FreeTypeFont:
    for path in paths:
        try:
            return ImageFont.truetype(path, size)
        except OSError:
            continue
    return ImageFont.load_default(size)  # last-resort fallback


_MONO = ["C:/Windows/Fonts/consola.ttf", "/System/Library/Fonts/Menlo.ttc", "DejaVuSansMono.ttf"]
_MONO_BOLD = ["C:/Windows/Fonts/consolab.ttf", "/System/Library/Fonts/Menlo.ttc", "DejaVuSansMono-Bold.ttf"]

font = _font(_MONO, 15 * SCALE)
font_bold = _font(_MONO_BOLD, 15 * SCALE)
font_title = _font(_MONO, 12 * SCALE)

CHAR_W = font.getlength("m")  # monospace: every glyph the same width
LINE_H = 26
COMMAND = "ward scan ."


def base_canvas() -> tuple[Image.Image, ImageDraw.ImageDraw]:
    img = Image.new("RGB", (W, H), BG)
    draw = ImageDraw.Draw(img)
    draw.rounded_rectangle([0, 0, W - 1, H - 1], radius=12 * SCALE, fill=BG, outline=BORDER, width=2)
    draw.rectangle([2, 2, W - 3, 34 * SCALE], fill=TITLEBAR)
    for cx, color in ((22, "#ff5f56"), (44, "#ffbd2e"), (66, "#27c93f")):
        draw.ellipse([(cx - 6) * SCALE, 11 * SCALE, (cx + 6) * SCALE, 23 * SCALE], fill=color)
    title = "ward — CortexWard"
    draw.text(((W - draw.textlength(title, font=font_title)) / 2, 11 * SCALE), title,
              font=font_title, fill=TITLE_TEXT)
    return img, draw


Seg = tuple[float, str, str, ImageFont.FreeTypeFont]


def text_at(draw: ImageDraw.ImageDraw, x: float, y: int, s: str, color: str,
            f: ImageFont.FreeTypeFont = font) -> None:
    draw.text((x * SCALE, y * SCALE), s, font=f, fill=color)


def row(draw: ImageDraw.ImageDraw, y: int, segments: list[Seg]) -> None:
    for x, s, color, f in segments:
        text_at(draw, x, y, s, color, f)


# Output lines of the real `ward scan .` human format, top to bottom.
HEADER_Y = 58
COLS = (20, 130, 250, 380, 500)  # severity, rule, location, state, finding
OUTPUT = [
    (HEADER_Y, [(20, "CortexWard", CYAN, font_bold), (20 + 11 * CHAR_W / SCALE, " scanning .", FG, font_bold)]),
    (HEADER_Y + LINE_H, [(20, "· 4 scanner(s) · static scanners", DIM, font)]),
    (HEADER_Y + LINE_H * 2 + 6, [(c, h, DIM, font) for c, h in zip(
        COLS, ("severity", "rule", "location", "state", "finding"))]),
    (HEADER_Y + LINE_H * 3 + 6, [(COLS[0], "CRITICAL", CRIT, font), (COLS[1], "CW-secret", DIM, font),
        (COLS[2], "config.py:2", CYAN, font), (COLS[3], "triaged", FG, font),
        (COLS[4], "hard-coded credential", FG, font)]),
    (HEADER_Y + LINE_H * 4 + 6, [(COLS[0], "HIGH", HIGH, font), (COLS[1], "B602", DIM, font),
        (COLS[2], "app.py:5", CYAN, font), (COLS[3], "candidate", FG, font),
        (COLS[4], "subprocess call, shell=True", FG, font)]),
    (HEADER_Y + LINE_H * 5 + 6, [(COLS[0], "MEDIUM", MED, font), (COLS[1], "B608", DIM, font),
        (COLS[2], "db.py:12", CYAN, font), (COLS[3], "candidate", FG, font),
        (COLS[4], "SQL from string concat", FG, font)]),
    (HEADER_Y + LINE_H * 6 + 14, [(20, "1 critical · 1 high · 1 medium · 3 total", DIM, font)]),
    (HEADER_Y + LINE_H * 7 + 14, [(20, "→ Next: --format cortexward-json for full evidence", CYAN, font)]),
]
PROMPT_Y = 24


def cursor(draw: ImageDraw.ImageDraw, x: float, y: int) -> None:
    draw.rectangle([x * SCALE, (y - 1) * SCALE, (x + CHAR_W / SCALE) * SCALE, (y + 17) * SCALE], fill=FG)


def frame(typed: int, out_lines: int, cursor_on: bool, at_prompt: bool) -> Image.Image:
    img, draw = base_canvas()
    text_at(draw, 20, PROMPT_Y, "$", PROMPT, font_bold)
    text_at(draw, 38, PROMPT_Y, COMMAND[:typed], FG)
    if not at_prompt and cursor_on:  # cursor follows the typed command
        cursor(draw, 38 + typed * CHAR_W / SCALE, PROMPT_Y)
    for y, segs in OUTPUT[:out_lines]:
        row(draw, y, segs)
    if at_prompt:  # a fresh prompt with a blinking cursor after the run
        final_y = OUTPUT[-1][0] + LINE_H + 8
        text_at(draw, 20, final_y, "$", PROMPT, font_bold)
        if cursor_on:
            cursor(draw, 38, final_y)
    return img.resize((W // SCALE, H // SCALE), Image.LANCZOS)


frames: list[Image.Image] = []
durations: list[int] = []


def add(img: Image.Image, ms: int) -> None:
    frames.append(img)
    durations.append(ms)


# 1) Type the command, cursor blinking at the caret.
for i in range(len(COMMAND) + 1):
    add(frame(i, 0, cursor_on=True, at_prompt=False), 70)
add(frame(len(COMMAND), 0, cursor_on=True, at_prompt=False), 500)  # pause before Enter

# 2) Reveal output line by line.
reveal_ms = [420, 360, 500, 320, 320, 320, 460, 520]
for i in range(1, len(OUTPUT) + 1):
    add(frame(len(COMMAND), i, cursor_on=False, at_prompt=False), reveal_ms[i - 1])

# 3) Settle on a fresh prompt with a blinking cursor.
for _ in range(3):
    add(frame(len(COMMAND), len(OUTPUT), cursor_on=True, at_prompt=True), 550)
    add(frame(len(COMMAND), len(OUTPUT), cursor_on=False, at_prompt=True), 450)

out_path = Path(__file__).parent / "demo-terminal.gif"
frames[0].save(out_path, save_all=True, append_images=frames[1:], duration=durations, loop=0, optimize=True)
print(f"wrote {out_path} ({len(frames)} frames)")
