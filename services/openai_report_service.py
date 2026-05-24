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
import sys
from pathlib import Path
from typing import Any

try:
    from dotenv import load_dotenv
    import dotenv as _dotenv_package
    DOTENV_IMPORT_STATUS = "success"
    DOTENV_PACKAGE_PATH = getattr(_dotenv_package, "__file__", "")
except ModuleNotFoundError as exc:
    DOTENV_IMPORT_STATUS = f"failed: {exc}"
    DOTENV_PACKAGE_PATH = ""

    def load_dotenv(dotenv_path=None, override=False):
        path = Path(dotenv_path) if dotenv_path else Path(".env")
        if not path.is_file():
            return False
        loaded_any = False
        for raw_line in path.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            if not key:
                continue
            if override or key not in os.environ:
                os.environ[key] = value
                loaded_any = True
        return loaded_any

log = logging.getLogger(__name__)
SERVICE_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SERVICE_DIR.parent
ENV_PATH = PROJECT_ROOT / ".env"

print("[OpenAI Report] PYTHON_EXECUTABLE:", sys.executable)
print("[OpenAI Report] DOTENV_IMPORT_STATUS:", DOTENV_IMPORT_STATUS)
print("[OpenAI Report] DOTENV_PACKAGE_PATH:", DOTENV_PACKAGE_PATH)
print("[OpenAI Report] ENV_PATH:", ENV_PATH)
print("[OpenAI Report] ENV_PATH_EXISTS:", ENV_PATH.exists())

TASK_FIELDS = (
    "sap_notification",
    "site_id",
    "problem",
    "vendor",
    "approach",
    "action_taken",
    "current_status",
    "comment",
)

REPORT_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "tasks": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "sap_notification": {"type": "string"},
                    "site_id": {"type": "string"},
                    "problem": {"type": "string"},
                    "vendor": {"type": "string"},
                    "approach": {"type": "string"},
                    "action_taken": {"type": "string"},
                    "current_status": {"type": "string"},
                    "comment": {"type": "string"},
                },
                "required": list(TASK_FIELDS),
            },
        },
    },
    "required": ["tasks"],
}

SYSTEM_PROMPT = """
You are an intelligent maintenance reporting assistant.
Extract ALL visible maintenance task rows from the uploaded supervisor assignment image.

Return JSON only in this exact structure:
{
  "tasks": [
    {
      "sap_notification": "",
      "site_id": "",
      "problem": "",
      "vendor": "",
      "approach": "",
      "action_taken": "",
      "current_status": "",
      "comment": ""
    }
  ]
}

Rules:
- Extract every visible table row, not just the first row.
- Each table row must become one object in the tasks array.
- If there are 3 visible task rows, return 3 task objects.
- If there are 10 visible task rows, return 10 task objects.
- Map SAP Notification, Notification, Ticket Number, or SAP number to sap_notification.
- Map Site ID, Site Code, or Site to site_id.
- Map Issue, Problem, Fault, or Description to problem.
- Never invent information.
- If a field is missing, hidden, cropped, ambiguous, or unclear, return an empty string.
- Preserve SAP numbers exactly as shown when readable.
- Preserve Site ID formatting as much as possible, for example RYDRL 4694 WB or RYDRL4694-EB.
- Understand maintenance terminology, assignment screenshots, ticket tables,
  technical issue descriptions, vendors, status labels, and field-service workflow.
- Do not include markdown, explanations, confidence scores, or extra keys.
""".strip()


class OpenAIReportExtractionError(RuntimeError):
    """Raised when OpenAI Vision extraction cannot return valid report JSON."""


def extract_report_from_image(image_path: str, timeout_seconds: float = 40.0) -> dict[str, list[dict[str, str]]]:
    """
    Extract maintenance report fields from an uploaded image using OpenAI Vision.

    Parameters
    ----------
    image_path:
        Local path to the uploaded image.
    timeout_seconds:
        OpenAI request timeout. Keep below the frontend timeout.
    """
    api_key = _get_openai_api_key()
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
                                "Analyze this maintenance supervisor assignment table image. "
                                "Extract every visible row as a separate task object in the tasks array."
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


def _parse_report_json(output_text: str) -> dict[str, list[dict[str, str]]]:
    log.info("[OpenAI Report] JSON parsing started")
    if not output_text or not output_text.strip():
        raise OpenAIReportExtractionError("OpenAI returned an empty response.")

    try:
        parsed = json.loads(output_text)
    except json.JSONDecodeError as exc:
        log.exception("[OpenAI Report] JSON parsing failed output=%r", output_text[:1000])
        raise OpenAIReportExtractionError(f"OpenAI returned invalid JSON: {exc}") from exc

    report = _normalize_report(parsed)
    log.info("[OpenAI Report] JSON parsing succeeded tasks=%s", len(report["tasks"]))
    log.info("[OpenAI Report] final parsed JSON structure=%s", report)
    return report


def _normalize_report(value: Any) -> dict[str, list[dict[str, str]]]:
    if isinstance(value, list):
        raw_tasks = value
    elif isinstance(value, dict) and isinstance(value.get("tasks"), list):
        raw_tasks = value["tasks"]
    elif isinstance(value, dict) and isinstance(value.get("tasks"), dict):
        raw_tasks = [value["tasks"]]
    elif isinstance(value, dict):
        raw_tasks = [value]
    else:
        raise OpenAIReportExtractionError("OpenAI JSON response was not an object or tasks array.")

    tasks: list[dict[str, str]] = []
    for raw_task in raw_tasks:
        if not isinstance(raw_task, dict):
            continue

        task = {}
        for field in TASK_FIELDS:
            raw_value = raw_task.get(field, "")
            task[field] = raw_value.strip() if isinstance(raw_value, str) else ""

        if any(task.values()):
            tasks.append(task)

    log.info("[OpenAI Report] number of tasks extracted=%s", len(tasks))
    return {"tasks": tasks}


def _get_openai_api_key() -> str:
    api_key = os.environ.get("OPENAI_API_KEY", "").strip()
    if api_key:
        log.info("[OpenAI Report] OPENAI_API_KEY already loaded length=%s", len(api_key))
        return api_key

    loaded = load_dotenv(dotenv_path=ENV_PATH, override=False)
    api_key = os.environ.get("OPENAI_API_KEY", "").strip()
    print("[OpenAI Report] DOTENV_FALLBACK_LOADED:", loaded)
    print("[OpenAI Report] OPENAI_API_KEY_LOADED:", bool(api_key))
    print("[OpenAI Report] OPENAI_API_KEY_LENGTH:", len(api_key))
    log.info(
        "[OpenAI Report] dotenv fallback loaded=%s path=%s exists=%s key_loaded=%s",
        loaded,
        ENV_PATH,
        ENV_PATH.exists(),
        bool(api_key),
    )
    return api_key
