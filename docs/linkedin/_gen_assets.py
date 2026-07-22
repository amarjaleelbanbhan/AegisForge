"""Generator for the LinkedIn post visuals (docs/linkedin/assets/*.png).

One consistent visual identity across all five cards: GitHub-dark background,
the CortexWard shield + wordmark, a cyan accent, the CLI's own severity colors,
and a repo-URL footer. 1200x1200 (LinkedIn feed square, also fine for GitHub).

Run (Pillow is only needed here):

    uv run --with pillow python docs/linkedin/_gen_assets.py
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

S = 1200
BG = "#0d1117"
PANEL = "#161b22"
BORDER = "#30363d"
FG = "#e6edf3"
DIM = "#8b949e"
ACCENT = "#39c5cf"
BLUE = "#58a6ff"
CRIT = "#ff7b72"
HIGH = "#f85149"
MED = "#d29922"
GREEN = "#3fb950"
REPO = "github.com/amarjaleelbanbhan/CortexWard"

_SANS = ["C:/Windows/Fonts/segoeui.ttf", "/System/Library/Fonts/SFNS.ttf", "DejaVuSans.ttf"]
_SANS_B = ["C:/Windows/Fonts/segoeuib.ttf", "/System/Library/Fonts/SFNS.ttf", "DejaVuSans-Bold.ttf"]
_MONO = ["C:/Windows/Fonts/consola.ttf", "/System/Library/Fonts/Menlo.ttc", "DejaVuSansMono.ttf"]


def _font(paths: list[str], size: int) -> ImageFont.FreeTypeFont:
    for p in paths:
        try:
            return ImageFont.truetype(p, size)
        except OSError:
            continue
    return ImageFont.load_default(size)


F_HUGE = _font(_SANS_B, 92)
F_H1 = _font(_SANS_B, 62)
F_H2 = _font(_SANS_B, 44)
F_BODY = _font(_SANS, 38)
F_SMALL = _font(_SANS, 30)
F_MONO = _font(_MONO, 34)
F_MONO_S = _font(_MONO, 28)


def shield(draw: ImageDraw.ImageDraw, cx: int, cy: int, w: int, color: str) -> None:
    h = int(w * 1.2)
    pts = [
        (cx, cy - h // 2), (cx + w // 2, cy - h // 2 + h // 6),
        (cx + w // 2, cy + h // 8), (cx, cy + h // 2),
        (cx - w // 2, cy + h // 8), (cx - w // 2, cy - h // 2 + h // 6),
    ]
    draw.polygon(pts, fill=color)
    # a check mark
    draw.line([(cx - w // 5, cy), (cx - w // 20, cy + w // 6), (cx + w // 4, cy - w // 5)],
              fill=BG, width=10, joint="curve")


def canvas() -> tuple[Image.Image, ImageDraw.ImageDraw]:
    img = Image.new("RGB", (S, S), BG)
    d = ImageDraw.Draw(img)
    d.rectangle([0, 0, S, 8], fill=ACCENT)  # top accent bar
    # brand row
    shield(d, 70, 78, 56, ACCENT)
    d.text((112, 46), "CortexWard", font=F_H2, fill=FG)
    # footer
    d.line([(60, S - 96), (S - 60, S - 96)], fill=BORDER, width=2)
    d.text((60, S - 78), REPO, font=F_SMALL, fill=DIM)
    d.text((S - 60 - d.textlength("Apache-2.0", font=F_SMALL), S - 78),
           "Apache-2.0", font=F_SMALL, fill=DIM)
    return img, d


def chip(d: ImageDraw.ImageDraw, x: int, y: int, text: str, color: str) -> int:
    w = int(d.textlength(text, font=F_SMALL)) + 40
    d.rounded_rectangle([x, y, x + w, y + 52], radius=26, outline=color, width=2)
    d.text((x + 20, y + 8), text, font=F_SMALL, fill=color)
    return x + w + 18


def save(img: Image.Image, name: str) -> None:
    out = Path(__file__).parent / "assets" / name
    out.parent.mkdir(exist_ok=True)
    img.save(out)
    print(f"wrote {out}")


# --- 01 Project launch ------------------------------------------------------
def launch() -> None:
    img, d = canvas()
    d.text((60, 210), "An autonomous AI", font=F_HUGE, fill=FG)
    d.text((60, 300), "security engineer", font=F_HUGE, fill=ACCENT)
    d.text((60, 430), "that proves a vulnerability is exploitable —", font=F_H2, fill=FG)
    d.text((60, 486), "then proves the fix.", font=F_H2, fill=FG)
    d.text((60, 600), "Evidence decides, not the model.", font=F_BODY, fill=DIM)
    x = 60
    for label, color in (("Verification Ladder", ACCENT), ("VEX output", BLUE),
                         ("Docker-sandboxed PoC", GREEN)):
        x = chip(d, x, 700, label, color)
    x = 60
    for label, color in (("Python", DIM), ("Apache-2.0", DIM), ("100% coverage", GREEN),
                         ("mypy-strict", DIM)):
        x = chip(d, x, 780, label, color)
    save(img, "01-project-launch.png")


# --- 02 Technical deep dive: the ladder -------------------------------------
def deep_dive() -> None:
    img, d = canvas()
    d.text((60, 180), "The Verification Ladder", font=F_H1, fill=FG)
    d.text((60, 260), "a finding is only as trustworthy as its strongest evidence",
           font=F_SMALL, fill=DIM)
    rungs = [
        ("NONE", "pattern match", DIM),
        ("STATIC_REACHABILITY", "sink reachable from an entrypoint", BLUE),
        ("TAINT_CONFIRMED", "attacker data flows to the sink", MED),
        ("DYNAMIC_POC", "exploit ran in a sandbox", HIGH),
        ("DIFFERENTIAL_TEST", "vulnerable vs. fixed, distinguished", GREEN),
    ]
    y = 360
    for i, (name, desc, color) in enumerate(rungs):
        d.rectangle([60, y + 8, 60 + 40 + i * 60, y + 40], fill=color)  # ascending bar
        d.text((60 + 40 + len(rungs) * 60 + 30, y), name, font=F_MONO, fill=color)
        d.text((60 + 40 + len(rungs) * 60 + 30, y + 44), desc, font=F_SMALL, fill=DIM)
        y += 118
    d.text((60, 980), "confidence = logistic(Σ signed log-odds weights)", font=F_MONO_S, fill=FG)
    d.text((60, 1024), "an LLM can never, by construction, reach 'verified' alone.",
           font=F_SMALL, fill=ACCENT)
    save(img, "02-technical-deep-dive.png")


# --- 03 Building journey ----------------------------------------------------
def journey() -> None:
    img, d = canvas()
    d.text((60, 190), "3 sandbox bugs only a", font=F_H1, fill=FG)
    d.text((60, 262), "real Docker daemon", font=F_H1, fill=ACCENT)
    d.text((60, 334), "could find", font=F_H1, fill=FG)
    items = [
        ("Docker refuses `docker cp` into a read-only container",
         "→ build the PoC into an image layer instead"),
        ("tmpfs is torn down before artifacts can be copied out",
         "→ use a daemon-managed named volume"),
        ("a fresh named volume is root-owned",
         "→ chown the mount point at build time"),
    ]
    y = 470
    for title, fix in items:
        d.text((60, y), title, font=F_BODY, fill=FG)
        d.text((90, y + 52), fix, font=F_SMALL, fill=GREEN)
        y += 150
    d.text((60, 1010), "infrastructure is never the ideal on paper.", font=F_SMALL, fill=DIM)
    save(img, "03-building-journey.png")


# --- 04 Open-source contribution --------------------------------------------
def contribution() -> None:
    img, d = canvas()
    d.text((60, 200), "Built to be extended.", font=F_H1, fill=FG)
    d.text((60, 290), "Come build it with me.", font=F_H1, fill=ACCENT)
    d.text((60, 400), "Most capabilities are plugin adapters behind clean ports —",
           font=F_SMALL, fill=DIM)
    d.text((60, 438), "add one without touching the core.", font=F_SMALL, fill=DIM)
    areas = [
        "a new scanner adapter (ScannerPort)",
        "a new reporter (SARIF, CSAF-VEX, ...)",
        "live-test the Anthropic / Gemini adapters",
        "cross-file taint — the CPG's biggest lever",
        "docs, examples, a getting-started guide",
    ]
    y = 520
    for a in areas:
        d.text((70, y), "›", font=F_H2, fill=ACCENT)
        d.text((120, y + 6), a, font=F_BODY, fill=FG)
        y += 82
    chip(d, 60, y + 10, "good first issues welcome", GREEN)
    save(img, "04-open-source-contribution.png")


# --- 05 Feature spotlight: the closed loop ----------------------------------
def spotlight() -> None:
    img, d = canvas()
    d.text((60, 190), "Prove the exploit.", font=F_H1, fill=FG)
    d.text((60, 262), "Prove the fix.", font=F_H1, fill=ACCENT)
    steps = [
        ("1", "scanner flags a command injection", DIM),
        ("2", "CPG proves the sink is reachable", BLUE),
        ("3", "a PoC runs in an isolated Docker sandbox", HIGH),
        ("4", "marker fires → DYNAMIC_POC → VERIFIED", GREEN),
        ("5", "patch passes all 4 gates — incl. re-running", ACCENT),
        (" ", "the same PoC against the patched code", ACCENT),
    ]
    y = 380
    for n, text, color in steps:
        if n.strip():
            d.ellipse([60, y, 108, y + 48], outline=color, width=3)
            d.text((76, y + 4), n, font=F_H2, fill=color)
        d.text((130, y + 4), text, font=F_BODY, fill=FG if n.strip() else color)
        y += 96 if n.strip() else 60
    d.text((60, 1010), "not 'AI thinks it's a bug' — here's the exploit, and proof the fix kills it.",
           font=F_SMALL, fill=DIM)
    save(img, "05-feature-spotlight.png")


for fn in (launch, deep_dive, journey, contribution, spotlight):
    fn()
print("done")
