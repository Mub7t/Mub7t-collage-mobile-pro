"""
supervisor_image_service.py
───────────────────────────
Extract the supervisor email table rows used to auto-fill the daily report.

This service intentionally extracts only the three fields needed from the
supervisor screenshot: SAP Notification, Site ID, and Issue.
"""

from __future__ import annotations

import re

from services.ocr_service import extract_text_from_image
from services.parser_service import (
    DEFAULT_COMMENT,
    DEFAULT_STATUS,
    DEFAULT_VENDOR,
)


RE_SAP = re.compile(r"\b(\d{7,10})\b")
RE_SPACED_SAP = re.compile(r"(?<!\d)((?:\d[\s.\-]*){7,10})(?!\d)")
RE_SITE = re.compile(
    r"\b(R\s*Y\s*D\s*R\s*[LI1])\s*(\d\s*\d\s*\d\s*\d)(?:\s*([A-D]))?\b",
    re.IGNORECASE,
)
RE_HEADER = re.compile(r"\b(sap|notification|site|issue|problem)\b", re.IGNORECASE)
RE_ROW_PREFIX = re.compile(r"^\s*(?:#\s*)?\d{1,3}(?:[.)\-|]\s+|\s+)")
RE_TABLE_CHARS = re.compile(r"[|_═─—]+")


def extract_supervisor_rows_from_image(image_path: str) -> tuple[str, list[dict[str, str]]]:
    """
    Full supervisor-image extraction pipeline.

    First run page-level OCR, then parse the text. If the screenshot contains a
    bordered table, also run cell-level OCR from detected grid boxes and merge
    those rows with the text parser results.
    """
    raw_text = extract_text_from_image(image_path).strip()
    text_rows = extract_supervisor_rows(raw_text) if raw_text else []
    grid_rows = _extract_rows_by_grid(image_path)
    print("PARSED ROWS grid:", grid_rows)

    if len(grid_rows) >= len(text_rows):
        merged = _merge_rows(grid_rows, text_rows)
    else:
        merged = _merge_rows(text_rows, grid_rows)
    print("FINAL EXTRACTED DATA:", merged)
    return raw_text, merged


def extract_supervisor_rows(raw_text: str) -> list[dict[str, str]]:
    """
    Parse OCR text from a supervisor screenshot into report source rows.

    OCR engines usually preserve each table row on a single line for this
    screenshot shape. The fallback parser also handles cases where the table
    columns are split across adjacent lines.
    """
    if not raw_text or not raw_text.strip():
        return []

    print("OCR RAW TEXT:", raw_text)

    lines = _clean_lines(raw_text)
    print("OCR CLEAN LINES:", lines)

    rows = _parse_single_line_rows(lines)
    print("PARSED ROWS single_line:", rows)

    if not rows:
        rows = _parse_columnar_rows(lines)
        print("PARSED ROWS columnar:", rows)

    if not rows:
        rows = _parse_multiline_rows(lines)
        print("PARSED ROWS multiline:", rows)

    if not rows:
        rows = _parse_stream_rows("\n".join(lines))
        print("PARSED ROWS stream:", rows)

    final_rows = _dedupe_valid_rows(rows)
    print("FINAL EXTRACTED DATA:", final_rows)
    return final_rows


def rows_to_report_tasks(rows: list[dict[str, str]]) -> list[dict]:
    """Map extracted supervisor rows into the existing daily report task shape."""
    tasks = []
    for i, row in enumerate(rows, start=1):
        sap = _clean_value(row.get("sapNotification", ""))
        site = _clean_site_id(row.get("siteId", ""))
        issue = _clean_value(row.get("issue", ""))
        if not sap or not site:
            continue
        tasks.append({
            "row_num": i,
            "task": "Field Service",
            "site_id": site,
            "approach": "N/A",
            "problem": issue,
            "vendor": DEFAULT_VENDOR,
            "sap_notification": sap,
            "action_taken": "",
            "current_status": DEFAULT_STATUS,
            "comments": DEFAULT_COMMENT,
        })
    return tasks


def _clean_lines(raw_text: str) -> list[str]:
    lines = []
    for line in raw_text.splitlines():
        cleaned = RE_TABLE_CHARS.sub(" ", line)
        cleaned = RE_ROW_PREFIX.sub("", cleaned)
        cleaned = _normalise_ocr_text(cleaned)
        cleaned = re.sub(r"\s+", " ", cleaned).strip()
        if cleaned:
            lines.append(cleaned)
    return lines


def _parse_single_line_rows(lines: list[str]) -> list[dict[str, str]]:
    rows = []
    for line in lines:
        if _is_header_only(line):
            continue
        row_line = RE_ROW_PREFIX.sub("", line)
        sap_m = RE_SAP.search(row_line)
        site_m = RE_SITE.search(line)
        if not sap_m or not site_m:
            continue

        sap = sap_m.group(1)
        site = _site_from_match(site_m)
        issue = line[site_m.end():]
        issue = _cleanup_issue(issue)

        rows.append({
            "sapNotification": sap,
            "siteId": site,
            "issue": issue,
        })
    return rows


def _parse_multiline_rows(lines: list[str]) -> list[dict[str, str]]:
    rows = []
    index = 0
    while index < len(lines):
        line = lines[index]
        sap_m = RE_SAP.search(line)
        if not sap_m or _is_header_only(line):
            index += 1
            continue

        sap = sap_m.group(1)
        window = " ".join(lines[index:min(index + 5, len(lines))])
        site_m = RE_SITE.search(window)
        if not site_m:
            index += 1
            continue

        site = _site_from_match(site_m)
        issue = _cleanup_issue(window[site_m.end():])
        rows.append({
            "sapNotification": sap,
            "siteId": site,
            "issue": issue,
        })
        index += 1

    return rows


def _parse_columnar_rows(lines: list[str]) -> list[dict[str, str]]:
    """
    Fallback for OCR that reads a table column-by-column instead of row-by-row.
    """
    sap_values = []
    site_values = []
    issue_values = []

    for line in lines:
        if _is_header_only(line):
            continue
        row_line = RE_ROW_PREFIX.sub("", line)
        sap_values.extend(_sap_values(row_line))
        site_values.extend(_site_values(row_line))
        if not RE_SAP.search(row_line) and not RE_SITE.search(row_line):
            issue = _cleanup_issue(row_line)
            if _looks_like_issue(issue):
                issue_values.append(issue)

    count = min(len(sap_values), len(site_values))
    if count == 0:
        return []

    rows = []
    for i in range(count):
        rows.append({
            "sapNotification": sap_values[i],
            "siteId": site_values[i],
            "issue": issue_values[i] if i < len(issue_values) else "",
        })
    return rows


def _parse_stream_rows(text: str) -> list[dict[str, str]]:
    """
    Last-resort scanning fallback. It pairs SAP and Site IDs in reading order,
    then treats text after the Site ID up to the next SAP/Site pair as Issue.
    """
    rows = []
    for sap_m in RE_SAP.finditer(text):
        after_sap = text[sap_m.end():]
        site_m = RE_SITE.search(after_sap)
        if not site_m:
            continue
        site_abs_end = sap_m.end() + site_m.end()
        remainder = text[site_abs_end:]
        next_sap = RE_SAP.search(remainder)
        issue_region = remainder[:next_sap.start()] if next_sap else remainder
        rows.append({
            "sapNotification": sap_m.group(1),
            "siteId": _site_from_match(site_m),
            "issue": _cleanup_issue(issue_region),
        })
    return rows


def _dedupe_valid_rows(rows: list[dict[str, str]]) -> list[dict[str, str]]:
    valid_rows = []
    seen = set()
    for row in rows:
        sap = _clean_value(row.get("sapNotification", ""))
        site = _clean_site_id(row.get("siteId", ""))
        issue = _clean_value(row.get("issue", ""))
        if not sap or not site:
            continue
        key = (sap, site)
        if key in seen:
            continue
        seen.add(key)
        valid_rows.append({
            "sapNotification": sap,
            "siteId": site,
            "issue": issue,
        })
    return valid_rows


def _merge_rows(*row_groups: list[dict[str, str]]) -> list[dict[str, str]]:
    merged: dict[tuple[str, str], dict[str, str]] = {}
    order: list[tuple[str, str]] = []
    for group in row_groups:
        for row in _dedupe_valid_rows(group):
            key = (row["sapNotification"], row["siteId"])
            if key not in merged:
                merged[key] = row
                order.append(key)
                continue
            if len(row.get("issue", "")) > len(merged[key].get("issue", "")):
                merged[key] = row
    return [merged[key] for key in order]


def _extract_rows_by_grid(image_path: str) -> list[dict[str, str]]:
    try:
        import pytesseract
        from PIL import Image, ImageEnhance, ImageFilter, ImageOps
    except ImportError:
        return []

    try:
        img = Image.open(image_path)
    except Exception:
        return []

    gray = ImageOps.grayscale(img)
    gray = ImageOps.autocontrast(gray)
    width, height = gray.size
    if width < 1400:
        scale = 1400 / max(width, 1)
        gray = gray.resize((int(width * scale), int(height * scale)), Image.Resampling.LANCZOS)

    gray = ImageEnhance.Contrast(gray).enhance(2.0)
    gray = gray.filter(ImageFilter.SHARPEN)
    binary = gray.point(lambda px: 0 if px < 135 else 255)
    width, height = binary.size
    pixels = binary.load()

    y_lines = _line_centers([
        y for y in range(height)
        if sum(1 for x in range(width) if pixels[x, y] == 0) > width * 0.32
    ])
    x_lines = _line_centers([
        x for x in range(width)
        if sum(1 for y in range(height) if pixels[x, y] == 0) > height * 0.30
    ])

    y_lines = _filter_line_spacing(y_lines, 24)
    x_lines = _filter_line_spacing(x_lines, 45)
    if len(y_lines) < 3 or len(x_lines) < 4:
        return []

    # Tables may include a row-number column. If five vertical borders exist,
    # use columns 2-4 as SAP, Site ID, Issue. Otherwise use the first three.
    if len(x_lines) >= 5:
        sap_col, site_col, issue_col = 1, 2, 3
    else:
        sap_col, site_col, issue_col = 0, 1, 2

    rows = []
    for row_index in range(1, len(y_lines) - 1):
        y1, y2 = y_lines[row_index], y_lines[row_index + 1]
        if y2 - y1 < 22:
            continue
        try:
            sap = _ocr_cell(binary, x_lines[sap_col], y1, x_lines[sap_col + 1], y2, pytesseract, "sap")
            site = _ocr_cell(binary, x_lines[site_col], y1, x_lines[site_col + 1], y2, pytesseract, "site")
            issue = _ocr_cell(binary, x_lines[issue_col], y1, x_lines[issue_col + 1], y2, pytesseract, "issue")
        except Exception as exc:
            print(f"[OCR] grid cell failed row={row_index}: {exc}")
            continue

        sap_values = _sap_values(_normalise_ocr_text(sap))
        site_values = _site_values(_normalise_ocr_text(site))
        if not sap_values or not site_values:
            continue
        rows.append({
            "sapNotification": sap_values[0],
            "siteId": site_values[0],
            "issue": _cleanup_issue(issue),
        })

    return _dedupe_valid_rows(rows)


def _ocr_cell(binary_img, x1: int, y1: int, x2: int, y2: int, pytesseract, mode: str) -> str:
    margin_x = max(6, int((x2 - x1) * 0.04))
    margin_y = max(4, int((y2 - y1) * 0.12))
    crop = binary_img.crop((x1 + margin_x, y1 + margin_y, x2 - margin_x, y2 - margin_y))
    crop = crop.resize((crop.width * 2, crop.height * 2))

    config = "--oem 3 --psm 7 -c preserve_interword_spaces=1"
    if mode == "sap":
        config += " -c tessedit_char_whitelist=0123456789"
    elif mode == "site":
        config += " -c tessedit_char_whitelist=ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789 "

    text = pytesseract.image_to_string(crop, config=config)
    return re.sub(r"\s+", " ", text).strip()


def _line_centers(indices: list[int]) -> list[int]:
    if not indices:
        return []
    groups = []
    start = prev = indices[0]
    for value in indices[1:]:
        if value <= prev + 1:
            prev = value
            continue
        groups.append((start, prev))
        start = prev = value
    groups.append((start, prev))
    return [(start + end) // 2 for start, end in groups]


def _filter_line_spacing(lines: list[int], min_gap: int) -> list[int]:
    filtered = []
    for line in lines:
        if not filtered or line - filtered[-1] >= min_gap:
            filtered.append(line)
    return filtered


def _site_from_match(match: re.Match[str]) -> str:
    suffix = match.group(3).upper() if match.group(3) else ""
    prefix = re.sub(r"\s+", "", match.group(1).upper())
    prefix = prefix.replace("1", "L").replace("I", "L")
    number = re.sub(r"\D", "", match.group(2))
    parts = [prefix, number]
    if suffix:
        parts.append(suffix)
    return " ".join(parts)


def _cleanup_issue(value: str) -> str:
    issue = _normalise_ocr_text(value or "")
    issue = RE_ROW_PREFIX.sub("", issue)
    issue = re.sub(r"\b\d{7,10}\b", "", issue)
    issue = RE_SITE.sub("", issue)
    issue = RE_TABLE_CHARS.sub(" ", issue)
    issue = re.sub(r"\b\d{1,3}\b(?=\s|$)", "", issue)
    issue = re.sub(r"\b1s\b", "is", issue, flags=re.IGNORECASE)
    issue = re.sub(r"\s+", " ", issue).strip(" .,:;-")
    return _clean_value(issue)


def _clean_site_id(value: str) -> str:
    value = _clean_value(value)
    match = RE_SITE.search(value)
    if not match:
        return value
    return _site_from_match(match)


def _clean_value(value: str) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _is_header_only(line: str) -> bool:
    if RE_SAP.search(line):
        return False
    label = re.sub(r"[^a-z ]", " ", line.lower())
    label = re.sub(r"\s+", " ", label).strip()
    if label in {"sap", "notification", "sap notification", "site", "site id", "issue", "problem"}:
        return True
    return len(RE_HEADER.findall(line)) >= 2


def _normalise_ocr_text(value: str) -> str:
    text = str(value or "")
    text = text.replace("\u00a0", " ")
    text = re.sub(r"\bRYDR[1I]\b", "RYDRL", text, flags=re.IGNORECASE)
    text = re.sub(r"\bR\s*Y\s*D\s*R\s*[1I]\b", "RYDRL", text, flags=re.IGNORECASE)

    def compact_sap(match: re.Match[str]) -> str:
        raw = match.group(1)
        if re.fullmatch(r"\d\s+\d{7,10}[\s.\-]*", raw):
            return match.group(0)
        digits = re.sub(r"\D", "", raw)
        if 7 <= len(digits) <= 10:
            return digits + (" " if raw[-1:].isspace() else "")
        return match.group(0)

    return RE_SPACED_SAP.sub(compact_sap, text)


def _sap_values(line: str) -> list[str]:
    return [match.group(1) for match in RE_SAP.finditer(line)]


def _site_values(line: str) -> list[str]:
    return [_site_from_match(match) for match in RE_SITE.finditer(line)]


def _looks_like_issue(value: str) -> bool:
    if not value:
        return False
    if len(value) < 3:
        return False
    if re.fullmatch(r"(sap|notification|sap notification|site|site id|issue|problem)", value, re.IGNORECASE):
        return False
    if RE_SAP.search(value) or RE_SITE.search(value):
        return False
    return bool(re.search(r"[A-Za-z]", value))
