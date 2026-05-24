"""
ocr_service.py
--------------
Modular OCR service layer.

Current implementation uses EasyOCR.

To swap to a Vision AI service (OpenAI, Claude, Google Vision, etc.),
replace the body of `extract_text_from_image()` and keep the same
function signature: (image_path: str) -> str

The rest of the application only ever calls this one function.
"""

from functools import lru_cache
import os


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

    try:
        return _ocr_with_easyocr(image_path)
    except ImportError as exc:
        raise RuntimeError(
            "EasyOCR is not installed. Please run: pip install easyocr"
        ) from exc
    except Exception as exc:
        print(f"[OCR] EasyOCR failed: {exc}")
        raise RuntimeError("EasyOCR extraction failed.") from exc


@lru_cache(maxsize=1)
def _get_easyocr_reader():
    """
    Build the EasyOCR reader once per process.

    EasyOCR model initialization is expensive, and caching preserves the same
    service interface while avoiding repeated startup cost across uploads.
    """
    import easyocr  # type: ignore

    return easyocr.Reader(["en"], gpu=False, verbose=False)


def _ocr_with_easyocr(image_path: str) -> str:
    """
    Extract text using EasyOCR.

    Requires:
        pip install easyocr
    """
    reader = _get_easyocr_reader()
    results = reader.readtext(image_path, detail=0, paragraph=True)
    return "\n".join(results).strip()


# ---------------------------------------------------------------------------
# HOW TO CONNECT A VISION AI SERVICE (e.g., OpenAI or Claude)
# ---------------------------------------------------------------------------
#
# Replace `extract_text_from_image` with the following pattern:
#
# def extract_text_from_image(image_path: str) -> str:
#     import base64, httpx
#
#     with open(image_path, "rb") as f:
#         b64 = base64.b64encode(f.read()).decode()
#
#     # OpenAI Vision
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
#     # Claude Vision (Anthropic)
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
