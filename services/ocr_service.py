"""
ocr_service.py
──────────────
Modular OCR service layer.

Current implementation uses pytesseract + Pillow.

To swap to a Vision AI service (OpenAI, Claude, Google Vision …),
replace the body of `extract_text_from_image()` and keep the same
function signature:  (image_path: str) -> str

The rest of the application only ever calls this one function.
"""

import os
import shutil

# ── Optional: set Tesseract path on Windows ───────────────────────────────────
# import pytesseract
# pytesseract.pytesseract.tesseract_cmd = r"C:\Program Files\Tesseract-OCR\tesseract.exe"


def extract_text_from_image(image_path: str) -> str:
    """
    Extract all text from an image file and return it as a plain string.

    Parameters
    ----------
    image_path : str
        Absolute path to the uploaded image file.

    Returns
    -------
    str
        The full text extracted from the image.

    Raises
    ------
    RuntimeError
        When no OCR backend is available or extraction completely fails.
    """
    if not os.path.isfile(image_path):
        raise FileNotFoundError(f"Image not found: {image_path}")

    # ── Try pytesseract first ─────────────────────────────────────────────────
    try:
        return _ocr_with_pytesseract(image_path)
    except ImportError:
        pass  # pytesseract not installed — try next backend
    except Exception as exc:
        print(f"[OCR] pytesseract failed: {exc}")

    # ── Fallback: EasyOCR ─────────────────────────────────────────────────────
    try:
        return _ocr_with_easyocr(image_path)
    except ImportError:
        pass
    except Exception as exc:
        print(f"[OCR] EasyOCR failed: {exc}")

    # ── No backend available ──────────────────────────────────────────────────
    raise RuntimeError(
        "No OCR backend is installed. "
        "Please run: pip install pytesseract Pillow  "
        "(and install Tesseract on your OS), or: pip install easyocr"
    )


# ── Backend implementations ───────────────────────────────────────────────────

def _ocr_with_pytesseract(image_path: str) -> str:
    """
    Extract text using pytesseract.

    Requires:
        pip install pytesseract Pillow
        System: tesseract binary installed
    """
    import pytesseract

    if not shutil.which("tesseract"):
        raise RuntimeError(
            "Tesseract OCR is not installed or is not available in PATH. "
            "Install it with: brew install tesseract"
        )

    images = _build_preprocessed_images(image_path)
    configs = [
        "--oem 3 --psm 6 -c preserve_interword_spaces=1",
        "--oem 3 --psm 4 -c preserve_interword_spaces=1",
        "--oem 3 --psm 11 -c preserve_interword_spaces=1",
        "--oem 3 --psm 12 -c preserve_interword_spaces=1",
    ]

    candidates: list[str] = []
    for label, img in images:
        for config in configs:
            try:
                text = pytesseract.image_to_string(img, config=config).strip()
            except Exception as exc:
                print(f"[OCR] pytesseract variant failed label={label} config={config!r}: {exc}")
                continue
            if text and text not in candidates:
                print(f"[OCR] candidate label={label} config={config!r} chars={len(text)}")
                candidates.append(text)

    if not candidates:
        return ""

    # Keep all distinct OCR attempts. Table screenshots can be read better by
    # different PSM modes, and the parser can use any matching row from the
    # combined text.
    combined = "\n\n".join(candidates)
    print("OCR RAW TEXT:", combined)
    return combined.strip()


def _build_preprocessed_images(image_path: str):
    """
    Create OCR-friendly image variants for screenshots with tables.

    The variants target common failures: low contrast, thin text, table borders,
    small screenshots, and colored/anti-aliased UI captures.
    """
    from PIL import Image, ImageEnhance, ImageFilter, ImageOps

    original = Image.open(image_path)
    if original.mode not in ("RGB", "L"):
        original = original.convert("RGB")

    variants = []

    def upscale(img, min_width=1600):
        width, height = img.size
        if width >= min_width:
            return img
        scale = min_width / max(width, 1)
        return img.resize((int(width * scale), int(height * scale)), Image.Resampling.LANCZOS)

    base = upscale(original)
    variants.append(("upscaled-original", base))

    gray = ImageOps.grayscale(base)
    gray = ImageOps.autocontrast(gray)
    gray = ImageEnhance.Contrast(gray).enhance(2.2)
    gray = ImageEnhance.Sharpness(gray).enhance(2.0)
    gray = gray.filter(ImageFilter.SHARPEN)
    variants.append(("gray-contrast-sharp", gray))

    threshold = gray.point(lambda px: 255 if px > 178 else 0)
    variants.append(("threshold-178", threshold))

    softer_threshold = gray.filter(ImageFilter.MedianFilter(size=3))
    softer_threshold = softer_threshold.point(lambda px: 255 if px > 155 else 0)
    variants.append(("median-threshold-155", softer_threshold))

    inverted_guard = ImageOps.autocontrast(ImageOps.invert(gray))
    variants.append(("inverted-contrast", inverted_guard))

    return variants


def _ocr_with_easyocr(image_path: str) -> str:
    """
    Extract text using EasyOCR.

    Requires:
        pip install easyocr
    """
    import easyocr  # type: ignore

    reader = easyocr.Reader(["en"], verbose=False)
    results = reader.readtext(image_path, detail=0, paragraph=True)
    return "\n".join(results).strip()


# ── ─────────────────────────────────────────────────────────────────────────
# HOW TO CONNECT A VISION AI SERVICE (e.g., OpenAI or Claude)
# ─────────────────────────────────────────────────────────────────────────────
#
# Replace `extract_text_from_image` with the following pattern:
#
# def extract_text_from_image(image_path: str) -> str:
#     import base64, httpx
#
#     with open(image_path, "rb") as f:
#         b64 = base64.b64encode(f.read()).decode()
#
#     # ── OpenAI Vision ─────────────────────────────────────────────────────
#     # from openai import OpenAI
#     # client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])
#     # response = client.chat.completions.create(
#     #     model="gpt-4o",
#     #     messages=[{
#     #         "role": "user",
#     #         "content": [
#     #             {"type": "image_url",
#     #              "image_url": {"url": f"data:image/jpeg;base64,{b64}"}},
#     #             {"type": "text",
#     #              "text": "Extract ALL text from this email image verbatim."}
#     #         ]
#     #     }]
#     # )
#     # return response.choices[0].message.content
#
#     # ── Claude Vision (Anthropic) ─────────────────────────────────────────
#     # import anthropic
#     # client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
#     # response = client.messages.create(
#     #     model="claude-opus-4-5",
#     #     max_tokens=2048,
#     #     messages=[{
#     #         "role": "user",
#     #         "content": [
#     #             {"type": "image",
#     #              "source": {"type": "base64",
#     #                         "media_type": "image/jpeg",
#     #                         "data": b64}},
#     #             {"type": "text",
#     #              "text": "Extract ALL text from this email image verbatim."}
#     #         ]
#     #     }]
#     # )
#     # return response.content[0].text
