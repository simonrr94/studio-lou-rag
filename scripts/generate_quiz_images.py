"""
Generate the Design Style Quiz result images with OpenAI's image model (default)
or Nano Banana (Gemini image model).

One image per primary style x room = 20 images, written to static/quiz-images/
as <style-slug>-<room>.webp, which is exactly what design-style-quiz.html looks up.

Setup (once, on your machine, from the repo root):
    pip install openai pillow                # add google-genai only if using --provider gemini
    export OPENAI_API_KEY="your-key"         # Windows PowerShell: $env:OPENAI_API_KEY="your-key"

Run:
    python scripts/generate_quiz_images.py                     # all missing images
    python scripts/generate_quiz_images.py --provider gemini   # Nano Banana instead (needs GEMINI_API_KEY)
    python scripts/generate_quiz_images.py --only modern-living mid-century-modern-office
    python scripts/generate_quiz_images.py --force             # regenerate everything

Then open scripts/quiz_images_review.html in a browser to review the set.
Regenerate any misses with --only. Re-running without --force skips images
that already exist, so your approved images are never overwritten.
"""

import argparse
import io
import os
import re
import sys
import time
from pathlib import Path

import base64

try:
    from PIL import Image, ImageEnhance
except ImportError:
    sys.exit("Missing package. Run: pip install pillow")

# Tried in order until one works for your account. Override with OPENAI_IMAGE_MODEL.
OPENAI_MODELS = [m for m in [
    os.environ.get("OPENAI_IMAGE_MODEL"),
    "gpt-image-2.6-flare",
    "gpt-image-2.5-flare",
    "gpt-image-2.5-sunburst",
] if m]
GEMINI_MODEL = os.environ.get("GEMINI_IMAGE_MODEL", "gemini-2.5-flash-image")
REPO_ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = REPO_ROOT / "static" / "quiz-images"
REVIEW_PATH = Path(__file__).resolve().parent / "quiz_images_review.html"
WIDTH = 1200
QUALITY = 82

# ── STYLE DESCRIPTORS ──
# Two or three signals per style, not a checklist. Checklists make the model
# cram every signal into one room, which reads as a theme park.
STYLES = {
    "Modern": (
        "low, clean-lined furniture in soft neutral fabrics, light oak, a few matte black "
        "metal details, white plaster walls, a calm and edited room with a few carefully chosen objects"
    ),
    "Traditional": (
        "classic furniture with turned legs and rolled arms, warm wood with some age to it, "
        "a vintage rug, simple molding, a framed painting, patterns kept to one or two quiet prints"
    ),
    "Transitional": (
        "classic silhouettes simplified with clean lines, tailored upholstery in oatmeal and ivory "
        "linen, warm wood, a few brushed brass details, soft texture, very little pattern"
    ),
    "Mid-Century Modern": (
        "walnut and teak furniture with tapered legs and gentle curves, a low credenza, warm neutral "
        "walls and textiles, with olive, rust or mustard used only in one or two small accents such as "
        "a pillow or a ceramic; a solid or subtly textured rug; no multicolor geometric patterns, "
        "no brightly colored curtains, no colored accent wall"
    ),
    "Contemporary": (
        "a softly curved sofa or chair, a stone or travertine surface, layered tonal creams and warm greys "
        "with one deeper accent, mixed textures like boucle, linen and smoked glass, one sculptural light"
    ),
}

# ── ROOM DESCRIPTORS ──
ROOMS = {
    "living": "a living room with a sofa, coffee table, area rug and an accent chair",
    "bedroom": "a primary bedroom with a made bed and headboard, a nightstand, a rug and a reading chair or bench",
    "office": "a home office with a desk, a desk chair that suits the style, a task lamp and shelving; it reads as a real workspace",
    "dining": "a dining room with a table, chairs and a light fixture over the table, with a sideboard or console",
}

PROMPT_TEMPLATE = (
    "Professional interior photograph of {room} in a real, beautifully designed home, "
    "furnished in a {style} style: {descriptor}. "
    "Shot like a feature in a high-end shelter magazine: full-frame camera, 24mm lens at eye level, "
    "vertical lines kept straight, the whole room readable, composed slightly off-center rather than "
    "perfectly symmetrical. Bright, airy midday daylight from the windows, clean whites, accurate "
    "white balance, lamps off. Muted, true-to-life color with natural contrast, nothing oversaturated. "
    "Fully furnished and styled so it feels inspiring and lived in: books, ceramics, a throw, some greenery. "
    "No oversized flower arrangements, no repeated matching pairs everywhere. "
    "Photorealistic, with accurate material texture, natural shadows and realistic furniture proportions. "
    "It must look like a real photograph, not a 3D render or illustration. "
    "No people, no pets, no text, no logos, no watermarks."
)

# Post-processing for AI images only: pull saturation down so the set stays consistent.
SATURATION = 0.88


def slugify(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")


def build_jobs():
    for style, descriptor in STYLES.items():
        for room_key, room_desc in ROOMS.items():
            name = f"{slugify(style)}-{room_key}"
            prompt = PROMPT_TEMPLATE.format(room=room_desc, style=style, descriptor=descriptor)
            yield name, style, room_key, prompt


class AccountError(Exception):
    """A problem with the account or model access that will fail every image the same way."""


ACCOUNT_HINTS = ("verif", "does not exist", "model_not_found", "billing", "quota", "invalid_api_key", "incorrect api key")


def make_openai_generator():
    try:
        from openai import OpenAI
    except ImportError:
        sys.exit("Missing package. Run: pip install openai")
    if not os.environ.get("OPENAI_API_KEY"):
        sys.exit("Set OPENAI_API_KEY first (see the top of this file).")
    client = OpenAI()
    state = {"model": None}

    def call(model, prompt):
        result = client.images.generate(model=model, prompt=prompt, size="1536x1024", n=1)
        return Image.open(io.BytesIO(base64.b64decode(result.data[0].b64_json)))

    def generate(prompt: str) -> Image.Image:
        if state["model"]:
            return call(state["model"], prompt)
        last_error = None
        for model in OPENAI_MODELS:
            try:
                img = call(model, prompt)
                state["model"] = model
                print(f" [using {model}]", end="", flush=True)
                return img
            except Exception as e:
                if "does not exist" in str(e) or "model_not_found" in str(e):
                    last_error = e
                    continue
                raise
        raise AccountError(f"None of these models are available to your account: {', '.join(OPENAI_MODELS)}. Last error: {last_error}")

    return generate


def make_gemini_generator():
    try:
        from google import genai
        from google.genai import types
    except ImportError:
        sys.exit("Missing package. Run: pip install google-genai")
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        sys.exit("Set GEMINI_API_KEY first (see the top of this file).")
    client = genai.Client(api_key=api_key)

    def generate(prompt: str) -> Image.Image:
        return _gemini_generate(client, types, prompt)

    return generate


def _gemini_generate(client, types, prompt: str) -> Image.Image:
    response = client.models.generate_content(
        model=GEMINI_MODEL,
        contents=[prompt],
        config=types.GenerateContentConfig(
            response_modalities=["IMAGE"],
            image_config=types.ImageConfig(aspect_ratio="4:3"),
        ),
    )
    for part in response.candidates[0].content.parts:
        if getattr(part, "inline_data", None) and part.inline_data.data:
            return Image.open(io.BytesIO(part.inline_data.data))
    raise RuntimeError("No image returned (the request may have been blocked or the model returned text only).")


def save_webp(img: Image.Image, path: Path):
    img = img.convert("RGB")
    # Center-crop to 4:3 so every image matches the quiz frame exactly.
    target = 4 / 3
    if abs(img.width / img.height - target) > 0.01:
        if img.width / img.height > target:
            w = round(img.height * target)
            left = (img.width - w) // 2
            img = img.crop((left, 0, left + w, img.height))
        else:
            h = round(img.width / target)
            top = (img.height - h) // 2
            img = img.crop((0, top, img.width, top + h))
    if img.width > WIDTH:
        img = img.resize((WIDTH, round(img.height * WIDTH / img.width)), Image.LANCZOS)
    img.save(path, "WEBP", quality=QUALITY, method=6)


def write_review(jobs):
    cards = []
    for name, style, room_key, prompt in jobs:
        rel = f"../static/quiz-images/{name}.webp"
        exists = (OUT_DIR / f"{name}.webp").exists()
        img_html = f'<img src="{rel}?t={int(time.time())}" loading="lazy">' if exists else '<div class="missing">missing</div>'
        cards.append(
            f'<figure>{img_html}<figcaption><b>{name}</b><br>{style} · {room_key}</figcaption></figure>'
        )
    REVIEW_PATH.write_text(
        "<!doctype html><meta charset='utf-8'><title>Quiz image review</title>"
        "<style>body{font-family:sans-serif;background:#f5f0e8;margin:24px}"
        "h1{font-size:18px}.grid{display:grid;grid-template-columns:repeat(4,1fr);gap:16px}"
        "figure{margin:0;background:#fff;border-radius:10px;overflow:hidden}"
        "img,.missing{display:block;width:100%;aspect-ratio:4/3;object-fit:cover}"
        ".missing{background:#e9e2d6;display:flex;align-items:center;justify-content:center;color:#8a847e}"
        "figcaption{font-size:12px;padding:8px 10px}</style>"
        "<h1>Design Style Quiz images: rows are styles, columns are living, bedroom, office, dining</h1>"
        f"<div class='grid'>{''.join(cards)}</div>",
        encoding="utf-8",
    )


def import_photos(folder: Path, jobs):
    """Crop each downloaded photo to 4:3, resize, and save it under its quiz image name."""
    if not folder.is_dir():
        sys.exit(f"Folder not found: {folder}")
    names = {j[0] for j in jobs}
    found = set()
    for f in sorted(folder.iterdir()):
        if f.suffix.lower() not in {".jpg", ".jpeg", ".png", ".webp"}:
            continue
        if f.stem not in names:
            print(f"ignore {f.name} (name doesn't match a quiz slot)")
            continue
        save_webp(Image.open(f), OUT_DIR / f"{f.stem}.webp")
        found.add(f.stem)
        print(f"import {f.stem}")
    missing = sorted(names - found)
    if missing:
        print("\nStill missing (the quiz hides the image for these):", " ".join(missing))


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--only", nargs="+", help="image names to (re)generate, e.g. modern-living")
    parser.add_argument("--force", action="store_true", help="overwrite existing images")
    parser.add_argument("--provider", choices=["openai", "gemini"], default="openai")
    parser.add_argument("--import-folder", metavar="FOLDER",
                        help="convert real photos named like modern-living.jpg in FOLDER into the quiz images (no AI)")
    args = parser.parse_args()

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    jobs = list(build_jobs())

    if args.import_folder:
        import_photos(Path(args.import_folder).expanduser(), jobs)
        write_review(jobs)
        print(f"\nReview sheet: {REVIEW_PATH}")
        return

    generate = make_openai_generator() if args.provider == "openai" else make_gemini_generator()

    if args.only:
        known = {j[0] for j in jobs}
        unknown = [n for n in args.only if n not in known]
        if unknown:
            sys.exit(f"Unknown image names: {', '.join(unknown)}\nValid names: {', '.join(sorted(known))}")

    failures = []
    for name, style, room_key, prompt in jobs:
        path = OUT_DIR / f"{name}.webp"
        if args.only and name not in args.only:
            continue
        if path.exists() and not (args.force or args.only):
            print(f"skip   {name} (exists)")
            continue
        print(f"make   {name} ...", end="", flush=True)
        try:
            img = ImageEnhance.Color(generate(prompt).convert("RGB")).enhance(SATURATION)
            save_webp(img, path)
            print(f" saved ({path.stat().st_size // 1024} KB)")
        except Exception as e:
            print(f" FAILED: {e}")
            failures.append(name)
            if isinstance(e, AccountError) or any(h in str(e).lower() for h in ACCOUNT_HINTS):
                print("\nStopping: this is an account or access problem, so every image would fail the same way.")
                break

    write_review(jobs)
    print(f"\nReview sheet: {REVIEW_PATH}")
    if failures:
        print("Failed, rerun with --only:", " ".join(failures))


if __name__ == "__main__":
    main()
