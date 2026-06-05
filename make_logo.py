from PIL import Image

# ── Claude-inspired asterisk logo ─────────────────────────────────────────────
#
# 6-arm asterisk (3 lines crossing at 60°):  vertical  +  two diagonals
# Warm terracotta on deep charcoal — Claude's visual identity.
#
# Legend:
#   . = Charcoal background
#   O = Claude coral / terracotta  (#d07050)
#   H = Bright highlight            (#e8a088)

PIXEL_ART = [
    "................",   # 0
    ".......OO.......",   # 1  top of vertical bar
    ".......OO.......",   # 2
    "..O....OO....O..",   # 3  diagonal arms appear
    "...O...OO...O...",   # 4
    "....HOOOOOOH....",   # 5  convergence zone
    "OOOHOOOOOOOHOOOO",   # 6  full horizontal bar
    "OOOHOOOOOOOHOOOO",   # 7  (2-pixel thick for weight)
    "....HOOOOOOH....",   # 8
    "...O...OO...O...",   # 9
    "..O....OO....O..",   # 10
    ".......OO.......",   # 11
    ".......OO.......",   # 12
    "................",   # 13
    "................",   # 14
    "................",   # 15
]

COLOR_PALETTE = {
    ".": (25,  24,  22),    # Deep charcoal  (#191816)
    "O": (208, 112, 80),    # Claude coral   (#d07050)
    "H": (232, 160, 136),   # Warm highlight (#e8a088)
}

def generate_logo(out_path="jarvis_logo.png", px_size=512):
    rows = len(PIXEL_ART)
    cols = len(PIXEL_ART[0])
    img  = Image.new("RGB", (cols, rows))
    pix  = img.load()

    for y, row in enumerate(PIXEL_ART):
        for x, ch in enumerate(row):
            pix[x, y] = COLOR_PALETTE.get(ch, (0, 0, 0))

    # Scale up with nearest-neighbour to preserve crisp pixel edges
    logo = img.resize((px_size, px_size), resample=Image.Resampling.NEAREST)
    logo.save(out_path)
    print(f"Logo saved → {out_path}  ({px_size}×{px_size}px)")

if __name__ == "__main__":
    generate_logo()