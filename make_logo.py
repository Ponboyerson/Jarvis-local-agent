from PIL import Image

# Define our crisp, 16x16 pixel matrix layout
# . = Background, C = Neon Cyan, B = Electric Blue, W = White Highlight
PIXEL_ART = [
    "....CCCCCC......",
    "..CCBBWWBBCC....",
    ".CBBWCCCCWBBC...",
    ".CBWCCCCCCWBC...",
    "CWCWW....WWCWC..",
    "CWCW..WW..WCWC..",
    "CWCW..WW..WCWC..",
    "CWCWW....WWCWC..",
    "CWC..WWWW..CWC..",
    ".CBW..WW..WBC...",
    ".CBBW....WBBC...",
    "..CCBBWWBBCC....",
    "....CCCCCC......",
    "......CC........",
    "................",
    "................"
]

# Map characters to precise RGB hex color values
COLOR_PALETTE = {
    ".": (17, 22, 37),    # Deep Space Charcoal (Background)
    "C": (0, 240, 255),   # Neon Cyan
    "B": (0, 102, 255),   # Electric Blue
    "W": (255, 255, 255)  # Pure White
}

def generate_logo():
    # 1. Create a tiny 16x16 canvas
    height = len(PIXEL_ART)
    width = len(PIXEL_ART[0])
    img = Image.new("RGB", (width, height))
    pixels = img.load()

    # 2. Paint the matrix pixel by pixel
    for y in range(height):
        for x in range(width):
            char = PIXEL_ART[y][x]
            pixels[x, y] = COLOR_PALETTE.get(char, (0, 0, 0))

    # 3. Blow it up to 512x512 using NEAREST to preserve crisp pixel edges
    output_size = (512, 512)
    crisp_logo = img.resize(output_size, resample=Image.Resampling.NEAREST)

    # 4. Save to your folder
    crisp_logo.save("jarvis_logo.png")
    print("🎯 Success! jarvis_logo.png generated cleanly in your project folder.")

if __name__ == "__main__":
    generate_logo()