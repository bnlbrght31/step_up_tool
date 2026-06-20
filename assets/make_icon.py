"""Generate the app icon (assets/icon.png, 1024x1024) for the SUFS launcher.

A blue rounded tile with a white receipt (torn bottom + line items) and a
green approval check badge. Run: python assets/make_icon.py
"""
from pathlib import Path
from PIL import Image, ImageDraw, ImageFilter

S = 1024
OUT = Path(__file__).with_name("icon.png")


def lerp(a, b, t):
    return tuple(int(a[i] + (b[i] - a[i]) * t) for i in range(len(a)))


def main():
    img = Image.new("RGBA", (S, S), (0, 0, 0, 0))

    # --- blue gradient clipped to a rounded tile ---------------------------
    grad = Image.new("RGBA", (S, S))
    gd = ImageDraw.Draw(grad)
    top, bot = (74, 160, 232, 255), (43, 108, 176, 255)
    for y in range(S):
        gd.line([(0, y), (S, y)], fill=lerp(top, bot, y / (S - 1)))
    mask = Image.new("L", (S, S), 0)
    ImageDraw.Draw(mask).rounded_rectangle([80, 80, S - 80, S - 80], radius=200, fill=255)
    img.paste(grad, (0, 0), mask)

    # --- soft drop shadow for the receipt ---------------------------------
    px0, px1, py0, py1 = 322, 702, 300, 712
    amp = 26
    shadow = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    ImageDraw.Draw(shadow).rectangle([px0, py0, px1, py1 + amp], fill=(20, 50, 90, 120))
    shadow = shadow.filter(ImageFilter.GaussianBlur(22))
    img.alpha_composite(shadow, (10, 18))

    # --- receipt paper (torn zig-zag bottom) ------------------------------
    teeth = 8
    step = (px1 - px0) / teeth
    pts = [(px0, py0), (px1, py0)]
    for i in range(teeth + 1):  # right -> left zig-zag
        x = px1 - i * step
        pts.append((x, py1 + (amp if i % 2 else 0)))
    draw = ImageDraw.Draw(img)
    draw.polygon(pts, fill=(255, 255, 255, 255))

    # line items
    line_c = (168, 178, 194, 255)
    for i, w in enumerate((300, 300, 230, 270, 180)):
        y = py0 + 70 + i * 78
        draw.rounded_rectangle([px0 + 40, y, px0 + 40 + w, y + 26], radius=13, fill=line_c)

    # --- green approval check badge ---------------------------------------
    cx, cy, r = S // 2, 700, 104
    draw.ellipse([cx - r, cy - r, cx + r, cy + r], fill=(56, 161, 105, 255))
    draw.ellipse([cx - r, cy - r, cx + r, cy + r], outline=(255, 255, 255, 255), width=12)
    check = [(cx - 46, cy + 2), (cx - 12, cy + 38), (cx + 52, cy - 40)]
    draw.line(check, fill=(255, 255, 255, 255), width=30, joint="curve")
    for p in (check[0], check[-1]):  # round the cap ends
        draw.ellipse([p[0] - 15, p[1] - 15, p[0] + 15, p[1] + 15], fill=(255, 255, 255, 255))

    img.save(OUT)
    print("wrote", OUT)


if __name__ == "__main__":
    main()
