"""One-off generator for docs/assets/demo-terminal.gif. Not part of the package
build; run manually and delete/regenerate as the demo script changes."""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

SCALE = 2
W, H = 760 * SCALE, 340 * SCALE
FONT_PATH = "C:/Windows/Fonts/consola.ttf"
FONT_BOLD_PATH = "C:/Windows/Fonts/consolab.ttf"

BG = "#0d1117"
TITLEBAR = "#22262e"
BORDER = "#30363d"
TITLE_TEXT = "#9da5b4"
PROMPT = "#58a6ff"
FG = "#e6edf3"
DIM = "#8b949e"
RED = "#f85149"
YELLOW = "#d29922"
GREEN = "#3fb950"

font = ImageFont.truetype(FONT_PATH, 15 * SCALE)
font_bold = ImageFont.truetype(FONT_BOLD_PATH, 15 * SCALE)
font_title = ImageFont.truetype(FONT_PATH, 13 * SCALE)


def base_canvas() -> tuple[Image.Image, ImageDraw.ImageDraw]:
    img = Image.new("RGB", (W, H), BG)
    draw = ImageDraw.Draw(img)
    draw.rectangle([0, 0, W, 36 * SCALE], fill=TITLEBAR)
    for cx, color in ((20, "#ff5f56"), (40, "#ffbd2e"), (60, "#27c93f")):
        draw.ellipse(
            [(cx - 6) * SCALE, (18 - 6) * SCALE, (cx + 6) * SCALE, (18 + 6) * SCALE], fill=color
        )
    title = "ward scan . — zsh"
    tw = draw.textlength(title, font=font_title)
    draw.text(((W - tw) / 2, 11 * SCALE), title, font=font_title, fill=TITLE_TEXT)
    draw.rounded_rectangle([0, 0, W - 1, H - 1], radius=12 * SCALE, outline=BORDER, width=2)
    return img, draw


Segment = tuple[int, str, str, ImageFont.FreeTypeFont]


def line(draw: ImageDraw.ImageDraw, y: int, segments: list[Segment]) -> None:
    for x, text, color, f in segments:
        draw.text((x * SCALE, y * SCALE), text, font=f, fill=color)


LINES = [
    [(20, "$", PROMPT, font), (38, "uv run ward scan . --format cortexward-json", FG, font)],
    [(20, "→ discovering scanners: bandit · semgrep · secrets · osv", DIM, font)],
    [(20, "→ scanning 42 files across 3 packages…", DIM, font)],
    [
        (20, "x app/db.py:42", RED, font),
        (180, "CWE-89 SQL Injection", FG, font),
        (600, "[HIGH]", RED, font_bold),
    ],
    [
        (20, "x app/auth.py:17", YELLOW, font),
        (180, "CWE-798 Hardcoded Credential", FG, font),
        (600, "[LOW]", YELLOW, font_bold),
    ],
    [(20, "→ correlating findings by CWE + location… 2 unique", DIM, font)],
    [(20, "→ verification ladder: reachability proof attached", DIM, font)],
    [(20, "Done in 1.8s — 2 findings (1 high, 1 low)", GREEN, font_bold)],
]

Y_POS = [66, 98, 124, 158, 184, 218, 244, 280]

frames: list[Image.Image] = []
durations: list[int] = []


def render_state(n_lines: int, cursor_on: bool) -> Image.Image:
    img, draw = base_canvas()
    for i in range(n_lines):
        line(draw, Y_POS[i], LINES[i])
    if n_lines == len(LINES):
        draw.text((20 * SCALE, 312 * SCALE), "$", font=font, fill=PROMPT)
        if cursor_on:
            draw.rectangle([38 * SCALE, 299 * SCALE, 47 * SCALE, 315 * SCALE], fill=FG)
    return img.resize((760, 340), Image.LANCZOS)


reveal_durations = [1100, 550, 550, 650, 650, 650, 650, 900]
for i in range(1, len(LINES) + 1):
    frames.append(render_state(i, cursor_on=False))
    durations.append(reveal_durations[i - 1])

for _ in range(3):
    frames.append(render_state(len(LINES), cursor_on=True))
    durations.append(500)
    frames.append(render_state(len(LINES), cursor_on=False))
    durations.append(500)

out_path = Path(__file__).parent / "demo-terminal.gif"
frames[0].save(
    out_path,
    save_all=True,
    append_images=frames[1:],
    duration=durations,
    loop=0,
    optimize=True,
)
print(f"wrote {out_path} ({len(frames)} frames)")
