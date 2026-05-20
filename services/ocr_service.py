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
    from PIL import Image, ImageEnhance, ImageFilter

    img = Image.open(image_path)

    # Basic pre-processing to improve OCR accuracy
    img = img.convert("L")                           # grayscale
    img = ImageEnhance.Contrast(img).enhance(2.0)   # boost contrast
    img = img.filter(ImageFilter.SHARPEN)            # sharpen edges

    config = "--psm 6 --oem 3"  # assume uniform block of text
    text = pytesseract.image_to_string(img, config=config)
    return text.strip()


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
