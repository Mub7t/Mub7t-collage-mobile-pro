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
import re
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
    "status",
    "approach",
    "vendor",
    "action_taken",
    "current_status",
    "comment",
)

SITE_ID_PATTERN = re.compile(r"RYDRL\s*\d{3,5}(?:(?:\s*-\s*|\s+)[A-Z]{1,3})?", re.IGNORECASE)
SAP_PATTERN = re.compile(r"\b\d{7,12}\b")

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
                    "status": {"type": "string"},
                    "approach": {"type": "string"},
                    "vendor": {"type": "string"},
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
      "status": "",
      "approach": "",
      "vendor": "",
      "action_taken": "",
      "current_status": "",
      "comment": ""
    }
  ]
}

Rules:
- Detect the layout automatically.
- Extract every visible maintenance task, not just the first task.
- The number of tasks is dynamic and not fixed.
- Each visible row, card, or task column must become one object in the tasks array.
- If there is 1 task, return 1 task object.
- If there are 2 task columns, return 2 task objects.
- If there are 5 task columns, return 5 task objects.
- If there are 10 table rows, return 10 task objects.
- Never merge multiple task columns into one task.
- Never hardcode the number of tasks.
- Format 1 vertical single-task card:
  Site / Approach, Problem name, Status, Work Order # describe one task.
- Format 2 multi-column task card:
  Site / Approach, Problem name, Status, Work Order # may have several task columns.
  Match each column vertically and return each column as a separate task.
- Format 3 Excel-like raw table without clear headers:
  Identify the problem/issue text, the SAP/work order number, and the site code from each row.
  Example row:
  10737932 | PM01 | 5/24/2026 | Rear Plate Image Clarity Issue | 70457992 | 5/24/2026 | 22085 | 0100-RA01-RUR-RUH-000RYDRL4646-EB
  should return problem Rear Plate Image Clarity Issue, sap_notification 70457992, site_id RYDRL4646-EB.
- Map Work Order #, SAP Notification, Notification, Ticket Number, or SAP number to sap_notification.
- Map Site / Approach, Site ID, Site Code, or Site to site_id when the value is a site code.
- Map Issue, Problem name, Problem, Fault, or Description to problem.
- Map visible Status values such as Pending or Solved to both status and current_status.
- Never invent information.
- If a field is missing, hidden, cropped, ambiguous, or unclear, return an empty string.
- Preserve SAP numbers exactly as shown when readable.
- Preserve Site ID formatting as much as possible, for example RYDRL 4694 WB or RYDRL4694-EB.
- If a Site ID appears inside a long technical location string, extract only the final site code,
  for example RYDRL4646-EB, RYDRL4177-B, or RYDRL4201-D.
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
                                "Detect whether it is a vertical card, multi-column card, or raw table. "
                                "Extract every visible maintenance task as a separate object in the tasks array."
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
        log.exception("[OpenAI Report] JSON parsing failed raw_ai_response=%r", output_text)
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
            raw_value = _read_task_field(raw_task, field)
            if isinstance(raw_value, str):
                value_text = raw_value.strip()
            elif raw_value is None:
                value_text = ""
            else:
                value_text = str(raw_value).strip()
            if field == "site_id":
                value_text = _clean_site_id(value_text)
            elif field == "sap_notification":
                value_text = _clean_sap_notification(value_text)
            task[field] = value_text

        if task["status"] and not task["current_status"]:
            task["current_status"] = task["status"]
        if task["current_status"] and not task["status"]:
            task["status"] = task["current_status"]

        if any(task.values()):
            tasks.append(task)

    log.info("[OpenAI Report] number of tasks extracted=%s", len(tasks))
    return {"tasks": tasks}


def _read_task_field(raw_task: dict[str, Any], field: str) -> Any:
    aliases = {
        "sap_notification": (
            "sap_notification",
            "sapNotification",
            "work_order",
            "work_order_number",
            "workOrder",
            "ticket_number",
            "ticketNumber",
            "notification",
        ),
        "site_id": ("site_id", "siteId", "site_code", "siteCode", "site", "site_approach", "location"),
        "problem": ("problem", "problem_name", "problemName", "issue", "description", "fault"),
        "status": ("status",),
        "vendor": ("vendor", "system_vendor", "systemVendor"),
        "approach": ("approach",),
        "action_taken": ("action_taken", "actionTaken", "action"),
        "current_status": ("current_status", "currentStatus"),
        "comment": ("comment", "comments", "notes"),
    }
    for key in aliases.get(field, (field,)):
        value = raw_task.get(key)
        if isinstance(value, str) and value.strip():
            return value
    return raw_task.get(field, "")


def _clean_site_id(value: str) -> str:
    if not value:
        return ""

    matches = SITE_ID_PATTERN.findall(value)
    if matches:
        site_id = matches[-1].strip()
        site_id = re.sub(r"\s*-\s*", "-", site_id)
        site_id = re.sub(r"\s+", " ", site_id)
        return site_id

    return value.strip()


def _clean_sap_notification(value: str) -> str:
    if not value:
        return ""

    matches = SAP_PATTERN.findall(value)
    if not matches:
        return value.strip()

    for match in matches:
        if match.startswith("704"):
            return match
    return matches[0]


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
