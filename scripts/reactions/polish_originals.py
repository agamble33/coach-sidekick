"""Build the "classic" pack: crop the phone UI out of the original meme
screenshots Tony sent, upscale, denoise, sharpen, and save to
assets/images/gen_classic/<name>.png (600x600). compose_cards.py turns those
into cards under assets/images/classic/.

Only the originals that are not owned characters or real people's faces are
used; the other triggers fall back to the 3D pack automatically.
"""
from pathlib import Path

from PIL import Image, ImageEnhance, ImageFilter, ImageOps

U = Path("/root/.claude/uploads/a54c07fa-90e5-5a70-9411-5f657e36d0b7")
OUT = Path(__file__).resolve().parent.parent / "assets" / "images" / "gen_classic"
OUT.mkdir(parents=True, exist_ok=True)

# name -> (file, crop box as fractions of width/height: left, top, right, bottom)
SRC = {
    "sleepy_dog": ("5f4b2f91", (0.00, 0.290, 1.00, 0.640)),
    "scream": ("2fd40390", (0.01, 0.300, 0.99, 0.700)),
    "stunned_cats": ("9db835fd", (0.05, 0.492, 0.95, 0.607)),  # row of three real cats only (no mascots)
    "horse_judge": ("d7a25e7b", (0.04, 0.240, 0.96, 0.765)),
    "side_eye": ("2eade54c", (0.00, 0.280, 1.00, 0.715)),
    "coach_selfie": ("0f5fa5e0", (0.04, 0.250, 0.96, 0.675)),
}


def square(im: Image.Image) -> Image.Image:
    w, h = im.size
    if w / h > 1.6:  # wide strip: letterbox onto dark card instead of cropping
        canvas = Image.new("RGB", (w, w), "#15171c")
        canvas.paste(im, (0, (w - h) // 2))
        return canvas
    s = min(w, h)
    return im.crop(((w - s) // 2, (h - s) // 2, (w - s) // 2 + s, (h - s) // 2 + s))


def polish(im: Image.Image) -> Image.Image:
    im = im.convert("RGB")
    # gentle denoise first (kills JPEG blockiness), then upscale, then sharpen
    im = im.filter(ImageFilter.MedianFilter(3))
    im = im.resize((600, 600), Image.LANCZOS)
    im = im.filter(ImageFilter.UnsharpMask(radius=2, percent=120, threshold=3))
    im = ImageOps.autocontrast(im, cutoff=1)
    im = ImageEnhance.Color(im).enhance(1.08)
    return im


if __name__ == "__main__":
    for name, (fid, (l, t, r, b)) in SRC.items():
        im = Image.open(U / f"{fid}-image.jpg")
        w, h = im.size
        im = im.crop((int(l * w), int(t * h), int(r * w), int(b * h)))
        im = polish(square(im))
        im.save(OUT / f"{name}.png")
        print("classic", name, im.size)
