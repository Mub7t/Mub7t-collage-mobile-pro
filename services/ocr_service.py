"""
ocr_service.py
──────────────
Modular OCR service layer.

Current implementation uses EasyOCR. This avoids any dependency on a
system-installed Tesseract binary, which is not available by default on Render.

To swap to a Vision AI service (OpenAI, Claude, Google Vision …),
replace the body of `extract_text_from_image()` and keep the same
function signature:  (image_path: str) -> str

The rest of the application only ever calls this one function.
"""

from functools import lru_cache
import logging
import os

log = logging.getLogger(__name__)


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
        When EasyOCR is unavailable or extraction completely fails.
    """
    if not os.path.isfile(image_path):
        raise FileNotFoundError(f"Image not found: {image_path}")

    file_size = os.path.getsize(image_path)
    log.info("[OCR] Starting EasyOCR extraction path=%s size=%s", image_path, file_size)

    try:
        text = _ocr_with_easyocr(image_path)
        log.info("[OCR] EasyOCR extraction completed chars=%s", len(text or ""))
        return text
    except ImportError as exc:
        log.exception("[OCR] EasyOCR import failed")
        raise RuntimeError(
            "EasyOCR is not installed in this environment. "
            "Add easyocr to requirements.txt and redeploy."
        ) from exc
    except Exception as exc:
        log.exception("[OCR] EasyOCR extraction failed")
        raise RuntimeError(f"EasyOCR extraction failed: {exc}") from exc


@lru_cache(maxsize=1)
def _get_easyocr_reader():
    """
    Build the EasyOCR reader once per process.

    Render instances have an ephemeral but writable /tmp directory. Storing
    EasyOCR model files there avoids home-directory permission issues.
    """
    import easyocr  # type: ignore

    model_dir = os.environ.get("EASYOCR_MODEL_DIR", "/tmp/easyocr_models")
    os.makedirs(model_dir, exist_ok=True)
    os.environ.setdefault("EASYOCR_MODULE_PATH", model_dir)

    log.info("[OCR] Initializing EasyOCR reader model_dir=%s", model_dir)
    return easyocr.Reader(
        ["en"],
        gpu=False,
        verbose=False,
        model_storage_directory=model_dir,
        user_network_directory=model_dir,
    )


def _ocr_with_easyocr(image_path: str) -> str:
    """
    Extract text using EasyOCR.

    Requires:
        pip install easyocr
    """
    reader = _get_easyocr_reader()
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
