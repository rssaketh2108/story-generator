# Copyright 2026 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     https://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import os
import urllib.request
import json
from PIL import Image, ImageDraw, ImageFont

# Directory for frontend public artifacts
ARTIFACTS_DIR = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "frontend", "public", "artifacts")
)

def ensure_artifacts_dir():
    os.makedirs(ARTIFACTS_DIR, exist_ok=True)

def _run_base(subdir: str = None) -> str:
    """Return the artifacts directory for a run (a per-run subfolder if given), creating it."""
    base = ARTIFACTS_DIR if not subdir else os.path.join(ARTIFACTS_DIR, subdir)
    os.makedirs(base, exist_ok=True)
    return base

def _artifact_path(filename: str, subdir: str = None) -> str:
    """Absolute path for an artifact, inside the per-run subfolder if given (dir created)."""
    return os.path.join(_run_base(subdir), filename)

def _artifact_url(filename: str, subdir: str = None) -> str:
    """Public URL path the frontend fetches (per-run subfolder if given)."""
    return f"/artifacts/{subdir}/{filename}" if subdir else f"/artifacts/{filename}"

def save_artifact_file(filename: str, content: str, subdir: str = None) -> dict:
    """Saves a markdown or text artifact to the public directory for the web app.

    Args:
        filename: The filename to save (e.g., 'characters.md', 'plot_outline.md').
        content: The text content of the artifact.
        subdir: Optional per-run subfolder so concurrent stories don't collide.

    Returns:
        A dictionary with the file path and status.
    """
    ensure_artifacts_dir()
    filepath = _artifact_path(filename, subdir)
    with open(filepath, "w", encoding="utf-8") as f:
        f.write(content)
    return {"status": "success", "filepath": _artifact_url(filename, subdir)}

def read_artifact_file(filename: str, subdir: str = None) -> dict:
    """Reads an existing artifact from the public directory.

    Args:
        filename: The name of the artifact file to read.
        subdir: Optional per-run subfolder to read from.

    Returns:
        A dictionary with the file content or an error message.
    """
    filepath = _artifact_path(filename, subdir)
    if not os.path.exists(filepath):
        return {"status": "error", "message": f"File {filename} not found."}
    with open(filepath, "r", encoding="utf-8") as f:
        content = f.read()
    return {"status": "success", "content": content}

def search_web_tool(query: str) -> dict:
    """Searches the web for theme details, visual concepts, or reference details.

    Args:
        query: The search query string.

    Returns:
        A dictionary containing simulated or fetched search results.
    """
    # Simple mock search with highly descriptive results to aid the writer room and illustrator
    results = [
        f"Concept art and reference details for '{query}': Typically features strong contrast, thematic color palettes.",
        f"Discussion forum thread about '{query}': Users suggest emphasizing distinct clothing patterns, specific expressions, and iconic props.",
        f"Visual history of '{query}': Often draws inspiration from classic literature, cyberpunk aesthetics, or fantasy lore."
    ]
    return {"status": "success", "query": query, "results": results}

# Comic panels don't need high-resolution art. Ideogram v4's smallest supported
# resolutions bottom out at ~1024 on the long side (there is no 640 option), so we
# request the smallest resolution per orientation.
# Orientation → (Ideogram resolution, placeholder width, placeholder height).
_ORIENTATIONS = {
    "landscape": ("1120x896", 640, 512),
    "portrait": ("896x1120", 512, 640),
    "square": ("1024x1024", 512, 512),
}

def _resolve_ref_path(p: str, subdir: str = None) -> str:
    """Resolve a reference-image reference (path or bare filename) to an absolute path."""
    if os.path.isabs(p):
        return p
    base = ARTIFACTS_DIR if not subdir else os.path.join(ARTIFACTS_DIR, subdir)
    return os.path.join(base, os.path.basename(p))

def _ideogram_generate(filepath, prompt, resolution, reference_paths=None):
    """Generate via Ideogram v4. Optionally condition on character reference images."""
    api_key = os.getenv("IDEOGRAM_API_KEY")
    if not api_key:
        return False
    try:
        import requests
        url = "https://api.ideogram.ai/v1/ideogram-v4/generate"
        # multipart/form-data with an "Api-Key" header (don't set Content-Type manually).
        parts = [("text_prompt", (None, prompt)), ("resolution", (None, resolution))]
        for p in (reference_paths or []):
            path = _resolve_ref_path(p)
            if os.path.exists(path):
                with open(path, "rb") as f:
                    parts.append(("character_reference_images", (os.path.basename(path), f.read(), "image/png")))
        res = requests.post(url, headers={"Api-Key": api_key}, files=parts, timeout=90)
        if res.status_code == 200:
            img_url = res.json()["data"][0]["url"]
            img_res = requests.get(img_url, timeout=60)
            if img_res.status_code == 200:
                with open(filepath, "wb") as f:
                    f.write(img_res.content)
                return True
        else:
            print(f"Ideogram error {res.status_code}: {res.text[:160]}")
    except Exception as e:
        print(f"Ideogram generation failed: {e}")
    return False

def _nanobanana_generate(filepath, prompt, orientation, reference_paths=None):
    """Generate via Nano Banana (gemini-2.5-flash-image). Character reference images are
    passed as multi-image input — this is how we get character consistency across panels."""
    gemini_key = os.getenv("GEMINI_API_KEY")
    if not gemini_key:
        return False
    try:
        from google import genai
        from google.genai import types as genai_types
        client = genai.Client(api_key=gemini_key)
        contents = []
        existing_refs = [ _resolve_ref_path(p) for p in (reference_paths or []) ]
        existing_refs = [ p for p in existing_refs if os.path.exists(p) ]
        if existing_refs:
            contents.append(
                "Below are reference images of the recurring characters in this comic. "
                "Reproduce these EXACT characters — same faces, hairstyles, and costumes — in the panel you generate:"
            )
            for p in existing_refs:
                contents.append(Image.open(p))
        contents.append(
            "Generate a single comic book panel illustration, digital comic art, cinematic lighting, "
            f"detailed, {orientation} orientation. Scene: {prompt}"
        )
        resp = client.models.generate_content(
            model="gemini-2.5-flash-image",
            contents=contents,
            config=genai_types.GenerateContentConfig(response_modalities=["IMAGE", "TEXT"]),
        )
        for candidate in (resp.candidates or []):
            content = getattr(candidate, "content", None)
            if not content or not getattr(content, "parts", None):
                continue  # safety-blocked or empty candidate
            for part in content.parts:
                inline = getattr(part, "inline_data", None)
                if inline and inline.data:
                    with open(filepath, "wb") as f:
                        f.write(inline.data)
                    return True
        print("Nano Banana returned no image data.")
    except Exception as e:
        print(f"Nano Banana generation failed: {e}")
    return False

def _placeholder_image(filepath, prompt, filename, W, H):
    """Draw a Pillow placeholder panel sized to the orientation (last-resort fallback)."""
    pad = max(6, W // 60)
    img = Image.new("RGB", (W, H), color=(34, 34, 34))
    draw = ImageDraw.Draw(img)
    draw.rectangle([pad, pad, W - pad, H - pad], outline=(238, 238, 238), width=4)

    hash_val = sum(ord(c) for c in prompt)
    r = (hash_val * 45) % 150 + 50
    g = (hash_val * 75) % 150 + 50
    b = (hash_val * 105) % 150 + 50
    art_bottom = int(H * 0.65)
    draw.rectangle([2 * pad, 2 * pad, W - 2 * pad, art_bottom], fill=(r, g, b))
    draw.rectangle([2 * pad, art_bottom + pad, W - 2 * pad, H - 2 * pad],
                   fill=(255, 255, 255), outline=(0, 0, 0), width=2)

    max_chars = max(20, W // 8)
    words = prompt.split()
    lines, current_line = [], []
    for word in words:
        if len(" ".join(current_line + [word])) < max_chars:
            current_line.append(word)
        else:
            lines.append(" ".join(current_line))
            current_line = [word]
    if current_line:
        lines.append(" ".join(current_line))

    text_x = 3 * pad
    draw.text((text_x, art_bottom + 2 * pad), "PANEL ACTION & VISUALS:", fill=(100, 100, 100))
    y_offset = art_bottom + 4 * pad
    max_lines = max(2, (H - art_bottom - 4 * pad) // 16)
    for line in lines[:max_lines]:
        draw.text((text_x, y_offset), line, fill=(0, 0, 0))
        y_offset += 16

    draw.rectangle([2 * pad, 2 * pad, 2 * pad + 130, 2 * pad + 24], fill=(0, 0, 0))
    draw.text((3 * pad, 2 * pad + 6), filename, fill=(255, 255, 255))
    img.save(filepath)

def generate_panel_image(filename: str, prompt: str, orientation: str = "landscape",
                         reference_images: list = None, subdir: str = None) -> dict:
    """Generates a comic panel image.

    Args:
        filename: Target filename (e.g., 'panel_1.png').
        prompt: Detailed description of the panel scene.
        orientation: 'landscape', 'portrait', or 'square' (chosen by the Head Writer).
        reference_images: Optional list of character-sheet image paths/filenames. When
            provided, the panel is conditioned on them for character consistency.
        subdir: Optional per-run subfolder so concurrent stories don't collide.

    Returns:
        A dict with the artifact filepath and status.
    """
    ensure_artifacts_dir()
    filepath = _artifact_path(filename, subdir)
    orientation = (orientation or "landscape").lower()
    resolution, ph_w, ph_h = _ORIENTATIONS.get(orientation, _ORIENTATIONS["landscape"])
    url = _artifact_url(filename, subdir)

    # Resolve reference images to absolute paths within this run's folder.
    abs_refs = [_resolve_ref_path(p, subdir) for p in (reference_images or [])]
    abs_refs = [p for p in abs_refs if os.path.exists(p)]

    if abs_refs:
        # Reference-conditioned panels → Nano Banana first (best multi-character consistency),
        # then Ideogram character-reference, then placeholder.
        print(f"Generating '{filename}' ({orientation}) with {len(abs_refs)} character reference(s) via Nano Banana...")
        if _nanobanana_generate(filepath, prompt, orientation, abs_refs):
            print(f"Saved Nano Banana (character-referenced) image to {filepath}")
            return {"status": "success", "filepath": url, "description": prompt}
        print(f"Nano Banana unavailable for '{filename}'; trying Ideogram character-reference...")
        if _ideogram_generate(filepath, prompt, resolution, abs_refs):
            print(f"Saved Ideogram (character-referenced) image to {filepath}")
            return {"status": "success", "filepath": url, "description": prompt}
    else:
        # Character sheets & panels with no cast → Ideogram first, then Nano Banana.
        print(f"Generating '{filename}' ({orientation}, {resolution}) via Ideogram...")
        if _ideogram_generate(filepath, prompt, resolution):
            print(f"Saved Ideogram image to {filepath}")
            return {"status": "success", "filepath": url, "description": prompt}
        print(f"Ideogram unavailable for '{filename}'; trying Nano Banana...")
        if _nanobanana_generate(filepath, prompt, orientation):
            print(f"Saved Nano Banana image to {filepath}")
            return {"status": "success", "filepath": url, "description": prompt}

    _placeholder_image(filepath, prompt, filename, ph_w, ph_h)
    print(f"Saved fallback Pillow mockup image to {filepath}")
    return {"status": "success", "filepath": url, "description": prompt}

def generate_character_sheet(name: str, description: str, filename: str, subdir: str = None) -> dict:
    """Generate a clean character reference sheet (used later to keep panels consistent).

    Args:
        name: Character name.
        description: Detailed visual description of the character.
        filename: Target filename (e.g., 'char_hero.png').
        subdir: Optional per-run subfolder.
    """
    prompt = (
        f"Character reference sheet of {name}. {description}. "
        "Full-body, front-facing, neutral plain light-grey background, no text, "
        "clear detailed character design, digital comic art, consistent style."
    )
    # Character sheets have no references themselves → Ideogram primary (per Option C).
    return generate_panel_image(filename, prompt, orientation="portrait", subdir=subdir)


# ── PDF export ─────────────────────────────────────────────────────────────────
# A4-ish portrait canvas at ~150 DPI. Pages are rendered as Pillow images and saved
# as a single multi-page PDF (no external PDF dependency needed).
_PDF_W, _PDF_H, _PDF_MARGIN = 1240, 1754, 80

def _load_font(size: int, bold: bool = False):
    candidates = [
        "/System/Library/Fonts/Supplemental/Arial Bold.ttf" if bold else "/System/Library/Fonts/Supplemental/Arial.ttf",
        "/System/Library/Fonts/Supplemental/Arial.ttf",
        "/System/Library/Fonts/Helvetica.ttc",
        "/Library/Fonts/Arial.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    ]
    for p in candidates:
        try:
            if os.path.exists(p):
                return ImageFont.truetype(p, size)
        except Exception:
            pass
    return ImageFont.load_default()

def _line_h(font) -> int:
    try:
        asc, desc = font.getmetrics()
        return asc + desc
    except Exception:
        return 22

def _wrap(draw, text: str, font, max_width: int) -> list:
    words = (text or "").split()
    lines, cur = [], ""
    for w in words:
        test = (cur + " " + w).strip()
        if draw.textlength(test, font=font) <= max_width or not cur:
            cur = test
        else:
            lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    return lines

def _load_display_font(size: int):
    """Heavy poster/comic display face (Impact-style) for the cover logo."""
    for p in ["/System/Library/Fonts/Supplemental/Impact.ttf",
              "/Library/Fonts/Impact.ttf",
              "/System/Library/Fonts/Supplemental/Arial Black.ttf"]:
        if os.path.exists(p):
            try:
                return ImageFont.truetype(p, size)
            except Exception:
                pass
    return _load_font(size, bold=True)

def _fit_cover(im, W, H):
    """Scale + center-crop an image so it completely fills a W×H frame."""
    ratio = max(W / im.width, H / im.height)
    nw, nh = int(im.width * ratio), int(im.height * ratio)
    im = im.resize((nw, nh))
    left, top = (nw - W) // 2, (nh - H) // 2
    return im.crop((left, top, left + W, top + H))

def _comic_cover_page(hero_path, title, genre, synopsis, W, H):
    """Render a Marvel/DC-style comic cover: full-bleed hero art + trade dress."""
    page = _fit_cover(Image.open(hero_path).convert("RGB"), W, H)

    # Dark scrims top and bottom so the logo and tagline stay legible over art.
    ov = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    od = ImageDraw.Draw(ov)
    th = int(H * 0.36)
    for y in range(th):
        od.line([(0, y), (W, y)], fill=(8, 9, 14, int(210 * (1 - y / th))))
    bh = int(H * 0.30)
    for k in range(bh):
        od.line([(0, H - 1 - k), (W, H - 1 - k)], fill=(8, 9, 14, int(220 * (1 - k / bh))))
    page = Image.alpha_composite(page.convert("RGBA"), ov).convert("RGB")

    d = ImageDraw.Draw(page)
    M = 60
    # Masthead + price
    small = _load_font(26, bold=True)
    d.text((M, 40), "THE WRITERS' ROOM COMICS", font=small, fill=(238, 238, 244))
    price = "$4.99"
    d.text((W - M - d.textlength(price, font=small), 40), price, font=small, fill=(238, 238, 244))
    # Issue badge
    d.text((M, 74), "No. 1", font=_load_display_font(42), fill=(232, 71, 59),
           stroke_width=2, stroke_fill=(0, 0, 0))
    # Genre kicker
    if genre:
        d.text((M, 156), genre.upper(), font=_load_font(30, bold=True), fill=(255, 210, 60))
    # Title logo — big Impact, black outline, wrapped to at most two lines
    title_u = (title or "Untitled").upper()
    size = 150
    tf = _load_display_font(size)
    lines = _wrap(d, title_u, tf, W - 2 * M)
    while len(lines) > 2 and size > 78:
        size -= 12
        tf = _load_display_font(size)
        lines = _wrap(d, title_u, tf, W - 2 * M)
    y = 196
    for ln in lines:
        d.text((M, y), ln, font=tf, fill=(255, 255, 255),
               stroke_width=max(4, size // 18), stroke_fill=(8, 9, 14))
        y += int(size * 0.98)
    # Tagline (first sentence of the synopsis), bottom
    tag = (synopsis or "").split(". ")[0].strip()
    if tag:
        if not tag.endswith("."):
            tag += "."
        tagf = _load_font(34)
        tl = _wrap(d, tag, tagf, W - 2 * M)[:3]
        ty = H - M - len(tl) * (_line_h(tagf) + 6)
        for ln in tl:
            d.text((M, ty), ln, font=tagf, fill=(246, 246, 249),
                   stroke_width=2, stroke_fill=(8, 9, 14))
            ty += _line_h(tagf) + 6
    return page

def build_comic_pdf(filename: str = "comic.pdf", subdir: str = None) -> dict:
    """Compile the generated comic into a multi-page PDF.

    Page 1 is a cover (title, genre, synopsis, cast thumbnails); the remaining pages
    show 2 panels each — the panel image with a caption box beneath it.
    Reads everything from comic_production.json in the (per-run) artifacts directory.
    """
    ensure_artifacts_dir()
    base = _run_base(subdir)
    prod_path = os.path.join(base, "comic_production.json")
    if not os.path.exists(prod_path):
        return {"status": "error", "message": "comic_production.json not found — generate a comic first."}
    with open(prod_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    title = (data.get("title") or "Untitled Comic").strip()
    synopsis = (data.get("synopsis") or "").strip()
    genre = (data.get("genre") or "").strip()
    characters = data.get("characters", []) or []
    panels = data.get("panels", []) or []

    W, H, M = _PDF_W, _PDF_H, _PDF_MARGIN
    content_w = W - 2 * M
    pages = []

    # ── Comic cover page (Marvel/DC style) — only if hero cover art was generated ──
    cover_name = data.get("cover_image")
    cover_art_path = os.path.join(base, cover_name) if cover_name else ""
    if cover_art_path and os.path.exists(cover_art_path):
        try:
            pages.append(_comic_cover_page(cover_art_path, title, genre, synopsis, W, H))
        except Exception as e:
            print(f"Comic cover render failed ({e}); using the text cover only.")

    # ── Text cover / credits page (title, synopsis, cast) ──
    cover = Image.new("RGB", (W, H), (18, 20, 28))
    d = ImageDraw.Draw(cover)
    title_font = _load_font(72, bold=True)
    sub_font = _load_font(34)
    body_font = _load_font(30)
    name_font = _load_font(26, bold=True)

    y = M + 30
    for line in _wrap(d, title, title_font, content_w):
        w = d.textlength(line, font=title_font)
        d.text(((W - w) / 2, y), line, font=title_font, fill=(240, 240, 245))
        y += _line_h(title_font) + 8
    y += 6
    if genre:
        w = d.textlength(genre, font=sub_font)
        d.text(((W - w) / 2, y), genre, font=sub_font, fill=(150, 160, 200))
        y += _line_h(sub_font) + 30
    if synopsis:
        for line in _wrap(d, synopsis, body_font, content_w):
            d.text((M, y), line, font=body_font, fill=(210, 214, 224))
            y += _line_h(body_font) + 6

    cast = [c for c in characters
            if c.get("filename") and os.path.exists(os.path.join(base, c["filename"]))]
    if cast:
        y += 40
        d.text((M, y), "CAST", font=name_font, fill=(150, 160, 200))
        y += _line_h(name_font) + 16
        n = len(cast)
        thumb_w = max(120, min(230, (content_w - 30 * (n - 1)) // n))
        x = M
        for c in cast:
            try:
                im = Image.open(os.path.join(base, c["filename"])).convert("RGB")
                th = int(im.height * (thumb_w / im.width))
                im = im.resize((thumb_w, th))
                cover.paste(im, (x, y))
                d.text((x, y + th + 8), (c.get("name") or "")[:22], font=name_font, fill=(230, 230, 235))
                x += thumb_w + 30
            except Exception:
                pass
    pages.append(cover)

    # ── Content pages: 2 panels per page ──
    cap_font = _load_font(28)
    num_font = _load_font(22, bold=True)
    slot_h = (H - 2 * M) // 2
    for i in range(0, len(panels), 2):
        page = Image.new("RGB", (W, H), (245, 245, 248))
        d = ImageDraw.Draw(page)
        for j, panel in enumerate(panels[i:i + 2]):
            slot_top = M + j * slot_h
            narration = (panel.get("narration") or "").strip()
            dialogue = (panel.get("dialogue") or panel.get("caption") or "").strip()
            cap_lines = []
            if narration:
                cap_lines += _wrap(d, narration, cap_font, content_w - 32)
            if dialogue:
                cap_lines += _wrap(d, f'“{dialogue}”', cap_font, content_w - 32)
            cap_lines = cap_lines[:6]
            cap_area = (len(cap_lines) * (_line_h(cap_font) + 4) + 24) if cap_lines else 0
            img_area_h = slot_h - cap_area - 40

            fp = os.path.join(base, panel.get("filename", ""))
            img_bottom = slot_top + 30
            if os.path.exists(fp) and img_area_h > 40:
                try:
                    im = Image.open(fp).convert("RGB")
                    ratio = min(content_w / im.width, img_area_h / im.height)
                    nw, nh = int(im.width * ratio), int(im.height * ratio)
                    im = im.resize((nw, nh))
                    ix = M + (content_w - nw) // 2
                    page.paste(im, (ix, slot_top + 30))
                    d.rectangle([ix, slot_top + 30, ix + nw, slot_top + 30 + nh], outline=(30, 30, 30), width=2)
                    img_bottom = slot_top + 30 + nh
                except Exception:
                    pass

            d.text((M, slot_top), f"Panel {i + j + 1}", font=num_font, fill=(120, 120, 130))
            if cap_lines:
                box_top = img_bottom + 12
                box_h = len(cap_lines) * (_line_h(cap_font) + 4) + 16
                d.rectangle([M, box_top, W - M, box_top + box_h], fill=(255, 255, 255), outline=(60, 60, 60), width=2)
                ty = box_top + 8
                for line in cap_lines:
                    d.text((M + 16, ty), line, font=cap_font, fill=(20, 20, 20))
                    ty += _line_h(cap_font) + 4

        d.text((W // 2, H - M + 24), str(i // 2 + 1), font=num_font, fill=(120, 120, 130))
        pages.append(page)

    pdf_path = os.path.join(base, filename)
    pages[0].save(pdf_path, save_all=True, append_images=pages[1:], format="PDF", resolution=150.0)
    print(f"Saved comic PDF ({len(pages)} pages) to {pdf_path}")
    return {"status": "success", "filepath": _artifact_url(filename, subdir), "pages": len(pages)}
