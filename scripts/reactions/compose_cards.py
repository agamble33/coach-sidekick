"""Compose final 512x512 reaction cards from assets/images/gen/*.png (3D renders)
rounded corners, bottom caption bar. Writes assets/images/*.png
and a contact sheet. Also rasterizes any gen/*.svg first."""
import asyncio
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont
from playwright.async_api import async_playwright

IMG = Path(__file__).resolve().parent.parent / "assets" / "images"
GEN = IMG / "gen"
CAPTIONS = {
    "sleepy_dog": "DID YOU SLEEP?",
    "horse_judge": "BRO.",
    "side_eye": "I SAID GO LEFT",
    "cackle": "HAHAHAHA",
    "scream": "NOOOOO",
    "stunned_cats": "WHAT WAS THAT",
    "big_brain": "BIG BRAIN",
    "rizz": "RIZZ DETECTED",
    "coach_selfie": "YOU SAW THAT?",
}


async def rasterize():
    svgs = sorted(GEN.glob("*.svg"))
    if not svgs:
        return
    async with async_playwright() as p:
        b = await p.chromium.launch()
        pg = await b.new_page(viewport={"width": 600, "height": 600})
        for s in svgs:
            await pg.goto(s.resolve().as_uri())
            await pg.screenshot(path=str(s.with_suffix(".png")))
        await b.close()


def card(src: Image.Image, caption: str) -> Image.Image:
    im = src.convert("RGB").resize((512, 512), Image.LANCZOS)
    mask = Image.new("L", (512, 512), 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, 511, 511), 48, fill=255)
    out = Image.new("RGBA", (512, 512), (0, 0, 0, 0))
    out.paste(im, (0, 0), mask)
    # caption bar: gradient fade so it sits on the render instead of cutting it
    bar = Image.new("RGBA", (512, 512), (0, 0, 0, 0))
    bd = ImageDraw.Draw(bar)
    for y in range(400, 512):
        a = int(230 * (y - 400) / 112)
        bd.line([(0, y), (511, y)], fill=(12, 13, 16, a))
    bar.putalpha(Image.composite(bar.getchannel("A"), Image.new("L", (512, 512), 0), mask))
    out = Image.alpha_composite(out, bar)
    d = ImageDraw.Draw(out)
    f = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 34)
    d.text((257, 472), caption, font=f, fill=(0, 0, 0, 160), anchor="mm")
    d.text((256, 470), caption, font=f, fill="#f2f3f5", anchor="mm")
    return out


def build_pack(src_dir: Path, out_dir: Path, sheet_name: str):
    out_dir.mkdir(parents=True, exist_ok=True)
    done = []
    for name, cap in CAPTIONS.items():
        p = src_dir / f"{name}.png"
        if p.exists():
            src = Image.open(p)
        else:
            continue  # pack doesn't cover this trigger; engine falls back to default pack
        card(src, cap).save(out_dir / f"{name}.png")
        done.append(name)
        print(out_dir.name, name)
    cols = 3
    rows = (len(done) + cols - 1) // cols
    sheet = Image.new("RGB", (cols * 256, rows * 256), "#000")
    for i, n in enumerate(done):
        sheet.paste(Image.open(out_dir / f"{n}.png").convert("RGB").resize((256, 256)), ((i % cols) * 256, (i // cols) * 256))
    sheet.save(IMG.parent / sheet_name)


def main():
    asyncio.run(rasterize())
    build_pack(GEN, IMG, "contact_sheet.png")                       # default "3d" pack


if __name__ == "__main__":
    main()
