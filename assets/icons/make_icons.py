import argparse
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont


def linear_gradient_rgba(size, top_rgb, bottom_rgb):
    """Create vertical linear gradient RGBA image."""
    w, h = size
    top = np.array(top_rgb, dtype=np.float32)
    bottom = np.array(bottom_rgb, dtype=np.float32)
    arr = np.zeros((h, w, 4), dtype=np.uint8)

    for y in range(h):
        t = y / (h - 1) if h > 1 else 0.0
        rgb = (top * (1 - t) + bottom * t).astype(np.uint8)
        arr[y, :, 0:3] = rgb
        arr[y, :, 3] = 255

    return Image.fromarray(arr)


def load_font(size_px: int):
    # Linux default path; falls back to default bitmap font if missing.
    try:
        return ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", size_px)
    except Exception:
        return ImageFont.load_default()


def fit_center(image: Image.Image, canvas_size: int, fill_ratio: float = 0.82) -> Image.Image:
    """
    Center-fit the icon into a square canvas while preserving aspect ratio.
    fill_ratio=0.82 means icon occupies ~82% of canvas width/height.
    """
    image = image.convert("RGBA")
    W = H = canvas_size

    # target box
    target = int(canvas_size * fill_ratio)
    iw, ih = image.size
    scale = min(target / iw, target / ih)
    new_w = max(1, int(round(iw * scale)))
    new_h = max(1, int(round(ih * scale)))

    icon = image.resize((new_w, new_h), Image.Resampling.LANCZOS)

    canvas = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    x = (W - new_w) // 2
    y = (H - new_h) // 2
    canvas.paste(icon, (x, y), icon)
    return canvas


def add_badge(canvas: Image.Image, text="2", badge_ratio=0.12):
    """Add red badge at top-right."""
    W, H = canvas.size
    out = canvas.copy()
    d = ImageDraw.Draw(out)

    r = int(W * badge_ratio)  # badge radius
    cx = int(W * 0.86)
    cy = int(H * 0.16)

    d.ellipse((cx - r, cy - r, cx + r, cy + r), fill=(220, 30, 30, 255))

    font = load_font(int(r * 1.25))
    bbox = d.textbbox((0, 0), text, font=font)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    d.text((cx - tw / 2, cy - th / 2 - int(H * 0.005)), text, fill=(255, 255, 255, 255), font=font)
    return out


def add_logout_arrow(canvas: Image.Image, arrow_center=(0.46, 0.57), arrow_scale=0.13):
    """
    Add a white 'exit' arrow overlay (kept minimal).
    arrow_center is relative (x,y) on canvas.
    """
    W, H = canvas.size
    out = canvas.copy()
    d = ImageDraw.Draw(out)

    cx = int(W * arrow_center[0])
    cy = int(H * arrow_center[1])

    aw = int(W * arrow_scale)
    ah = int(H * (arrow_scale * 0.65))

    pts = [
        (cx - int(aw * 0.55), cy - int(ah * 0.35)),
        (cx + int(aw * 0.05), cy - int(ah * 0.35)),
        (cx + int(aw * 0.05), cy - int(ah * 0.60)),
        (cx + int(aw * 0.60), cy),
        (cx + int(aw * 0.05), cy + int(ah * 0.60)),
        (cx + int(aw * 0.05), cy + int(ah * 0.35)),
        (cx - int(aw * 0.55), cy + int(ah * 0.35)),
    ]
    d.polygon(pts, fill=(255, 255, 255, 245))
    return out


def put_on_green_gradient(icon_canvas: Image.Image, top=(18, 120, 60), bottom=(85, 205, 125)):
    """Composite icon over green gradient background."""
    W, H = icon_canvas.size
    bg = linear_gradient_rgba((W, H), top, bottom)
    out = Image.alpha_composite(bg, icon_canvas.convert("RGBA"))
    return out


def export_png(img: Image.Image, path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    img.save(path, "PNG", optimize=True)


def export_ico_from_master(master_png: Image.Image, path: Path, sizes):
    """
    ICO best practice: create each size by downscaling from master with LANCZOS.
    Note: Many Windows UIs use up to 256x256. 512 is optional and not always used.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    base = master_png.convert("RGBA")
    imgs = [base.resize((s, s), Image.Resampling.LANCZOS) for s in sizes]
    # Pillow uses first image as base; sizes embedded
    imgs[0].save(path, format="ICO", sizes=[(s, s) for s in sizes])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", default="icon.png", help="Input icon PNG (prefer 1024x1024+).")
    ap.add_argument("--outdir", default="out_icons", help="Output directory.")
    ap.add_argument("--size", type=int, default=512, help="Target PNG size (e.g., 512).")
    ap.add_argument("--fill", type=float, default=0.82, help="How much the icon fills the canvas (0.7-0.9).")
    ap.add_argument("--no-ico", action="store_true", help="Do not export ICO.")
    ap.add_argument("--ico-sizes", default="256,128,64,48,32", help="Comma sizes for ICO (default: no 16).")
    args = ap.parse_args()

    inp = Path(args.input)
    outdir = Path(args.outdir)

    src = Image.open(inp).convert("RGBA")

    # Base canvas (transparent)
    base = fit_center(src, args.size, fill_ratio=args.fill)

    # Variants
    green_base = put_on_green_gradient(base)
    green_badge2 = add_badge(green_base, text="2")
    green_logout = add_logout_arrow(green_base)

    # Save PNGs
    export_png(base, outdir / f"Base_{args.size}.png")
    export_png(green_base, outdir / f"Green_{args.size}.png")
    export_png(green_badge2, outdir / f"Green_Badge2_{args.size}.png")
    export_png(green_logout, outdir / f"Green_Logout_{args.size}.png")

    # ICO (from master 512; embedded sizes should be <=256 for best compatibility)
    if not args.no_ico:
        sizes = [int(x.strip()) for x in args.ico_sizes.split(",") if x.strip()]
        # ICO sizes should not exceed master size
        sizes = [s for s in sizes if s <= args.size]
        if not sizes:
            raise SystemExit("ICO sizes list is empty or larger than --size.")
        export_ico_from_master(green_base, outdir / "App_Green.ico", sizes)
        export_ico_from_master(green_badge2, outdir / "App_Green_Badge2.ico", sizes)
        export_ico_from_master(green_logout, outdir / "App_Green_Logout.ico", sizes)

    print("Done. Output:", outdir.resolve())


if __name__ == "__main__":
    main()