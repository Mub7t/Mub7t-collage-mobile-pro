"""
parser_service.py  v5
─────────────────────
Key fixes in this version
─────────────────────────
1. OCR commonly confuses '1' (one) with 'l' (lowercase L) in approach codes
   like "A1" → "Al". We now normalise OCR output before regex matching.
2. Approach regex extended to match [A-Da-d][l1-9] then normalise l→1.
3. More robust row number stripping (handles plain-space separator).
4. PM lines stripped before any processing — never become task rows.
"""

import re
import logging
from typing import Any

log = logging.getLogger(__name__)

# ── Defaults ──────────────────────────────────────────────────────────────────
DEFAULT_VENDOR  = "N/A"
DEFAULT_COMMENT = "Waiting for RM confirmation"
DEFAULT_STATUS  = "Solved"

ACTION_SUGGESTIONS = {
    r"blur|blurry|blurred":                       "Cleaned the CCTV lens and verified image clarity.",
    r"camera.{0,20}offline|offline.{0,20}camera": "Checked camera power and network connection.",
    r"no[\s\-]signal":                             "Checked cable, power supply, and connection.",
    r"power\s+issue|power\s+failure|no\s+power":  "Checked power source, breaker, and power supply.",
    r"network|connectivity":                       "Checked network cable, switch port, and connectivity.",
    r"dirty.{0,10}lens|lens.{0,10}dirty":         "Cleaned the camera lens and verified image clarity.",
}

# ── Compiled patterns ─────────────────────────────────────────────────────────
RE_SAP  = re.compile(r"\b(\d{7,8})\b")
RE_SITE = re.compile(r"\b([A-Z]{2,6})\s*(\d{4})\b", re.IGNORECASE)

# Approach: letter A-D followed by digit 1-9 OR lowercase l (OCR confusion with 1)
RE_APPROACH = re.compile(r"\b([A-Da-d][l1-9])\b")

RE_PM = re.compile(
    r"(pm\s*level|conduct\s+pm|preventive\s+maintenance|also\s+conduct)",
    re.IGNORECASE,
)
RE_HEADER_WORDS = re.compile(
    r"\bsap\b|\bnotification\b|\bsite\b|\bissue\b|\bproblem\b|\btask\b",
    re.IGNORECASE,
)
# Row-number prefix: "1 " or "1. " or "1) " — optional punctuation, requires trailing space
RE_ROWNUM = re.compile(r"^\s*\d{1,2}\s*[.\-|)]?\s+")


# ── Public API ────────────────────────────────────────────────────────────────

def parse_email_text(text: str) -> dict[str, Any]:
    """Return {"supervisor": str, "team": str, "tasks": list[dict]}."""
    log.debug("=== RAW OCR ===\n%s", text)

    supervisor = _extract_supervisor(text)
    team       = _extract_team(text)
    log.debug("supervisor=%r  team=%r", supervisor, team)

    # Normalise OCR noise before cleaning
    text_norm = _normalise_ocr(text)
    clean     = _clean_text(text_norm)
    log.debug("=== CLEANED ===\n%s", clean)

    tasks = _extract_tasks(clean)
    log.debug("tasks=%d", len(tasks))
    for t in tasks:
        log.debug("  row=%d sap=%s site=%s approach=%s problem=%r",
                  t["row_num"], t["sap_notification"],
                  t["site_id"], t["approach"], t["problem"])

    return {"supervisor": supervisor, "team": team, "tasks": tasks}


# ── OCR normalisation ─────────────────────────────────────────────────────────

def _normalise_ocr(text: str) -> str:
    """
    Fix common OCR substitutions that break parsing:
    • Approach codes: 'Al' → 'A1', 'Bl' → 'B1', etc.
      (OCR often reads digit '1' as lowercase letter 'l')
    """
    # Replace patterns like " Al " or " Bl " that look like approach codes
    # Pattern: word boundary, single uppercase letter A-D, then lowercase l, word boundary
    text = re.sub(r"\b([A-D])l\b", lambda m: m.group(1) + "1", text)
    return text


# ── Text cleaning ─────────────────────────────────────────────────────────────

def _clean_text(text: str) -> str:
    lines = []
    for line in text.splitlines():
        stripped = line.strip()
        if RE_PM.search(stripped):
            log.debug("PM line removed: %r", stripped)
            continue
        cleaned = stripped.replace("|", " ").replace("\t", " ")
        cleaned = re.sub(r"  +", " ", cleaned)
        lines.append(cleaned)
    return "\n".join(lines)


# ── Supervisor ────────────────────────────────────────────────────────────────

def _extract_supervisor(text: str) -> str:
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    thanks_re = re.compile(
        r"thank\s*you|regards|sincerely|best\s+regards", re.IGNORECASE
    )
    name_re = re.compile(
        r"^([A-Z][A-Za-z'\-]{1,}(?:\s+[A-Z][A-Za-z'\-]{1,}){1,4})$"
    )
    found = False
    for line in lines:
        if thanks_re.search(line):
            found = True
            continue
        if found:
            m = name_re.match(line)
            if m:
                return m.group(1)
            if line:
                found = False

    # Fallback: line before job-title line
    title_re = re.compile(
        r"team[\s\-]?leader|manager|supervisor|acting|maintenance\s+team",
        re.IGNORECASE,
    )
    for i, line in enumerate(lines):
        if title_re.search(line) and i > 0:
            m = name_re.match(lines[i - 1])
            if m:
                return m.group(1)
    return ""


# ── Team ──────────────────────────────────────────────────────────────────────

def _extract_team(text: str) -> str:
    dear_re = re.compile(
        r"dear\s+([A-Za-z]+(?:\s*[&,]\s*[A-Za-z]+|\s+and\s+[A-Za-z]+)*)\s*[,.]",
        re.IGNORECASE,
    )
    m = dear_re.search(text)
    if m:
        raw = m.group(1).strip()
        raw = re.sub(r"\s*,\s*", " & ", raw)
        raw = re.sub(r"\s+and\s+", " & ", raw, flags=re.IGNORECASE)
        return raw
    return ""


# ── Task extraction ───────────────────────────────────────────────────────────

def _extract_tasks(text: str) -> list[dict]:
    tasks_a = _pass_single_line(text)
    if tasks_a:
        _number(tasks_a)
        return tasks_a
    tasks_b = _pass_multiline(text)
    _number(tasks_b)
    return tasks_b


# ── Pass A: single-line ───────────────────────────────────────────────────────

def _pass_single_line(text: str) -> list[dict]:
    tasks = []
    seen  = set()

    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        if _is_header_line(line):
            continue

        sap_m  = RE_SAP.search(line)
        site_m = RE_SITE.search(line)
        if not sap_m or not site_m:
            continue

        sap = sap_m.group(1)
        if sap in seen:
            continue

        # Build clean site ID with normalised spacing
        site_raw = site_m.group(1).upper() + " " + site_m.group(2)

        # Approach: immediately after site match
        after = line[site_m.end():].strip()
        ap_m  = RE_APPROACH.match(after)
        if ap_m:
            approach = ap_m.group(1).replace("l", "1").upper()
        else:
            approach = "N/A"

        problem = _extract_problem(line, sap, site_raw, approach)

        seen.add(sap)
        tasks.append(_build_task(
            site_id=site_raw, approach=approach,
            problem=problem, sap=sap,
            action=_suggest_action(problem),
        ))

    return tasks


# ── Pass B: multi-line fallback ───────────────────────────────────────────────

def _pass_multiline(text: str) -> list[dict]:
    lines = text.splitlines()
    tasks = []
    seen  = set()

    # Find all SAP numbers and their positions
    sap_positions: list[tuple[int, str]] = []
    for i, line in enumerate(lines):
        m = RE_SAP.search(line.strip())
        if m and not _is_header_line(line):
            sap_positions.append((i, m.group(1)))

    for line_idx, sap in sap_positions:
        if sap in seen:
            continue

        site_id  = "N/A"
        approach = "N/A"
        problem  = ""

        window = lines[max(0, line_idx - 1):min(len(lines), line_idx + 5)]

        for wline in window:
            wline = wline.strip()
            if not wline:
                continue
            if site_id == "N/A":
                sm = RE_SITE.search(wline)
                if sm:
                    site_id = sm.group(1).upper() + " " + sm.group(2)
                    after   = wline[sm.end():].strip()
                    apm     = RE_APPROACH.match(after)
                    if apm:
                        approach = apm.group(1).replace("l", "1").upper()
            if approach == "N/A":
                if re.fullmatch(r"[A-Da-d][l1-9]", wline.strip()):
                    approach = wline.strip().replace("l", "1").upper()
            if not problem:
                is_sap_only = bool(RE_SAP.fullmatch(wline.strip()))
                is_site     = bool(RE_SITE.search(wline))
                is_row_num  = bool(re.fullmatch(r"\d{1,2}", wline.strip()))
                is_approach = bool(re.fullmatch(r"[A-Da-d][l1-9]", wline.strip()))
                is_hdr      = _is_header_line(wline)
                if not is_sap_only and not is_site and not is_row_num \
                        and not is_approach and not is_hdr and len(wline) > 4:
                    if not RE_SAP.search(wline) or wline.strip() == sap:
                        problem = wline.strip()

        if site_id == "N/A":
            continue

        seen.add(sap)
        tasks.append(_build_task(
            site_id=site_id, approach=approach,
            problem=problem or "Not clear", sap=sap,
            action=_suggest_action(problem),
        ))

    return tasks


# ── Helpers ───────────────────────────────────────────────────────────────────

def _is_header_line(line: str) -> bool:
    """
    Only treat a line as a column header if:
    • it has >= 2 header-label keywords, AND
    • it does NOT contain a 7-8 digit SAP number.
    Data rows always have SAP numbers so they are never skipped.
    """
    if RE_SAP.search(line):
        return False
    return len(RE_HEADER_WORDS.findall(line)) >= 2


def _extract_problem(line: str, sap: str, site_id: str, approach: str) -> str:
    r = line
    r = RE_ROWNUM.sub("", r)
    r = r.replace(sap, "")
    site_no_sp = site_id.replace(" ", "")
    r = re.sub(re.escape(site_id),    "", r, flags=re.IGNORECASE)
    r = re.sub(re.escape(site_no_sp), "", r, flags=re.IGNORECASE)
    if approach != "N/A":
        # Also strip the 'l' version in case OCR put it back
        alt = approach[0] + "l"
        r = re.sub(r"\b" + re.escape(approach) + r"\b", "", r, flags=re.IGNORECASE)
        r = re.sub(r"\b" + re.escape(alt)       + r"\b", "", r, flags=re.IGNORECASE)
    r = re.sub(r"[|\\/:]+", " ", r)
    r = re.sub(r"\s+", " ", r).strip().strip(".,- ").strip()
    return r if len(r) > 2 else "Not clear"


def _number(tasks: list[dict]) -> None:
    for i, t in enumerate(tasks, start=1):
        t["row_num"] = i


def _build_task(
    site_id: str, approach: str, problem: str, sap: str,
    action: str   = "",
    comments: str = DEFAULT_COMMENT,
    status: str   = DEFAULT_STATUS,
    vendor: str   = DEFAULT_VENDOR,
) -> dict:
    return {
        "row_num": 0, "task": "Field Service",
        "site_id": site_id, "approach": approach,
        "problem": problem, "vendor": vendor,
        "sap_notification": sap, "action_taken": action,
        "current_status": status, "comments": comments,
    }


def _suggest_action(problem: str) -> str:
    if not problem or problem in ("Not clear", "N/A"):
        return ""
    for pattern, suggestion in ACTION_SUGGESTIONS.items():
        if re.search(pattern, problem, re.IGNORECASE):
            return suggestion
    return ""
