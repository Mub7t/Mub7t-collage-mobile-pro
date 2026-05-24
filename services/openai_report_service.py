"""
openai_report_service.py
────────────────────────
OpenAI Vision extraction service for maintenance report auto-fill.

This module reads an uploaded assignment/ticket image, sends it to the
OpenAI Responses API as a Base64 image input, and returns only the structured
maintenance fields used by the Flask app.
"""

from __future__ import annotations

import base64
import json
import logging
import mimetypes
import os
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

REPORT_FIELDS = (
    "site_code",
    "ticket_number",
    "system_vendor",
    "problem",
    "action",
    "status",
    "notes",
)

REPORT_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "site_code": {"type": "string"},
        "ticket_number": {"type": "string"},
        "system_vendor": {"type": "string"},
        "problem": {"type": "string"},
        "action": {"type": "string"},
        "status": {"type": "string"},
        "notes": {"type": "string"},
    },
    "required": list(REPORT_FIELDS),
}

SYSTEM_PROMPT = """
You are an intelligent maintenance reporting assistant.
Extract structured maintenance assignment details from the uploaded image.

Return JSON only with these exact keys:
site_code, ticket_number, system_vendor, problem, action, status, notes.

Rules:
- Never invent information.
- If a field is missing, hidden, cropped, ambiguous, or unclear, return an empty string.
- Preserve ticket/site identifiers exactly as shown when readable.
- Understand maintenance terminology, assignment screenshots, ticket tables,
  technical issue descriptions, vendors, status labels, and field-service workflow.
- Do not include markdown, explanations, confidence scores, or extra keys.
""".strip()


class OpenAIReportExtractionError(RuntimeError):
    """Raised when OpenAI Vision extraction cannot return valid report JSON."""


def extract_report_from_image(image_path: str, timeout_seconds: float = 40.0) -> dict[str, str]:
    """
    Extract maintenance report fields from an uploaded image using OpenAI Vision.

    Parameters
    ----------
    image_path:
        Local path to the uploaded image.
    timeout_seconds:
        OpenAI request timeout. Keep below the frontend timeout.
    """
    api_key = os.environ.get("OPENAI_API_KEY", "").strip()
    if not api_key:
        raise OpenAIReportExtractionError("OPENAI_API_KEY is not configured.")

    path = Path(image_path)
    if not path.is_file():
        raise OpenAIReportExtractionError(f"Image not found: {image_path}")
    if path.stat().st_size <= 0:
        raise OpenAIReportExtractionError("Uploaded image is empty.")

    mime_type = _guess_image_mime_type(path)
    image_data_url = _encode_image_data_url(path, mime_type)
    model = os.environ.get("OPENAI_REPORT_MODEL", "gpt-4.1-mini").strip() or "gpt-4.1-mini"

    log.info(
        "[OpenAI Report] request starting model=%s path=%s size=%s mime=%s",
        model,
        image_path,
        path.stat().st_size,
        mime_type,
    )

    try:
        from openai import APIConnectionError, APIError, APITimeoutError, OpenAI

        client = OpenAI(api_key=api_key, timeout=timeout_seconds)
        response = client.responses.create(
            model=model,
            input=[
                {
                    "role": "system",
                    "content": [{"type": "input_text", "text": SYSTEM_PROMPT}],
                },
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "input_text",
                            "text": (
                                "Analyze this maintenance assignment or ticket image. "
                                "Extract only the requested maintenance report fields as JSON."
                            ),
                        },
                        {
                            "type": "input_image",
                            "image_url": image_data_url,
                        },
                    ],
                },
            ],
            text={
                "format": {
                    "type": "json_schema",
                    "name": "maintenance_report_extraction",
                    "strict": True,
                    "schema": REPORT_SCHEMA,
                }
            },
        )
    except ImportError as exc:
        log.exception("[OpenAI Report] OpenAI SDK import failed")
        raise OpenAIReportExtractionError(
            "OpenAI SDK is not installed. Add openai to requirements.txt and redeploy."
        ) from exc
    except APITimeoutError as exc:
        log.exception("[OpenAI Report] OpenAI request timed out")
        raise OpenAIReportExtractionError("OpenAI Vision request timed out.") from exc
    except APIConnectionError as exc:
        log.exception("[OpenAI Report] OpenAI connection failed")
        raise OpenAIReportExtractionError(f"OpenAI connection failed: {exc}") from exc
    except APIError as exc:
        log.exception("[OpenAI Report] OpenAI API failure")
        raise OpenAIReportExtractionError(f"OpenAI API failure: {exc}") from exc
    except Exception as exc:
        log.exception("[OpenAI Report] OpenAI extraction failed")
        raise OpenAIReportExtractionError(f"OpenAI extraction failed: {exc}") from exc

    log.info("[OpenAI Report] API response received id=%s", getattr(response, "id", "unknown"))
    return _parse_report_json(response.output_text)


def _guess_image_mime_type(path: Path) -> str:
    mime_type, _ = mimetypes.guess_type(path.name)
    if mime_type in {"image/png", "image/jpeg", "image/webp", "image/gif"}:
        return mime_type

    suffix = path.suffix.lower()
    if suffix in {".jpg", ".jpeg"}:
        return "image/jpeg"
    if suffix == ".png":
        return "image/png"
    if suffix == ".webp":
        return "image/webp"

    raise OpenAIReportExtractionError("Invalid image type. Please upload PNG, JPG, JPEG, or WEBP.")


def _encode_image_data_url(path: Path, mime_type: str) -> str:
    try:
        encoded = base64.b64encode(path.read_bytes()).decode("utf-8")
    except OSError as exc:
        raise OpenAIReportExtractionError(f"Could not read uploaded image: {exc}") from exc
    return f"data:{mime_type};base64,{encoded}"


def _parse_report_json(output_text: str) -> dict[str, str]:
    log.info("[OpenAI Report] JSON parsing started")
    if not output_text or not output_text.strip():
        raise OpenAIReportExtractionError("OpenAI returned an empty response.")

    try:
        parsed = json.loads(output_text)
    except json.JSONDecodeError as exc:
        log.exception("[OpenAI Report] JSON parsing failed output=%r", output_text[:1000])
        raise OpenAIReportExtractionError(f"OpenAI returned invalid JSON: {exc}") from exc

    report = _normalize_report(parsed)
    log.info("[OpenAI Report] JSON parsing succeeded")
    return report


def _normalize_report(value: Any) -> dict[str, str]:
    if not isinstance(value, dict):
        raise OpenAIReportExtractionError("OpenAI JSON response was not an object.")

    normalized: dict[str, str] = {}
    for field in REPORT_FIELDS:
        raw_value = value.get(field, "")
        normalized[field] = raw_value.strip() if isinstance(raw_value, str) else ""

    return normalized
