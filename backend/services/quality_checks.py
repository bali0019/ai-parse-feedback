"""Auto-detect common ai_parse_document quality issues using heuristics."""

import re
import logging
import unicodedata
from collections import Counter

logger = logging.getLogger(__name__)


def run_quality_checks(parsed_result: dict) -> list[dict]:
    """Run heuristic quality checks on parsed ai_parse_document output.

    Returns list of flags: [{element_id, check, severity, message}]
    """
    flags = []
    document = parsed_result.get("document", {})
    elements = document.get("elements", [])

    for elem in elements:
        elem_id = elem.get("id")
        elem_type = elem.get("type", "")
        content = elem.get("content", "") or ""
        bbox_list = elem.get("bbox", [])

        # 1. Empty table cells
        if elem_type == "table" and content:
            flag = _check_empty_table_cells(elem_id, content)
            if flag:
                flags.append(flag)

            # 2. Column count mismatch
            flag = _check_column_mismatch(elem_id, content)
            if flag:
                flags.append(flag)

            # 3. Unclosed HTML tags
            flag = _check_unclosed_tags(elem_id, content)
            if flag:
                flags.append(flag)

        # 4. Possible checkbox (small empty text element)
        if elem_type == "text":
            flag = _check_possible_checkbox(elem_id, content, bbox_list)
            if flag:
                flags.append(flag)

            # 7. Suspicious numeric OCR
            flag = _check_numeric_ocr(elem_id, content)
            if flag:
                flags.append(flag)

        # 6. Mixed Unicode scripts
        if content:
            flag = _check_mixed_scripts(elem_id, content)
            if flag:
                flags.append(flag)

    # 5. Reading order anomalies (cross-element check)
    flags.extend(_check_reading_order(elements))

    logger.info(f"Quality checks complete: {len(flags)} flags found across {len(elements)} elements")
    return flags


def _check_empty_table_cells(elem_id: int, html: str) -> dict | None:
    """Flag tables where >50% of cells are empty."""
    cells = re.findall(r"<td[^>]*>(.*?)</td>", html, re.DOTALL | re.IGNORECASE)
    if len(cells) < 4:
        return None
    empty = sum(1 for c in cells if not c.strip())
    ratio = empty / len(cells)
    if ratio > 0.5:
        return {
            "element_id": elem_id,
            "check": "empty_table_cells",
            "severity": "warning",
            "message": f"Table has {int(ratio * 100)}% empty cells ({empty}/{len(cells)})",
        }
    return None


def _check_column_mismatch(elem_id: int, html: str) -> dict | None:
    """Flag tables where header column count != data column count."""
    header_cols = len(re.findall(r"<th[^>]*>", html, re.IGNORECASE))
    rows = re.findall(r"<tr[^>]*>(.*?)</tr>", html, re.DOTALL | re.IGNORECASE)
    if header_cols == 0 or len(rows) < 2:
        return None
    # Check first data row
    for row in rows[1:]:
        data_cols = len(re.findall(r"<td[^>]*>", row, re.IGNORECASE))
        if data_cols > 0 and data_cols != header_cols:
            return {
                "element_id": elem_id,
                "check": "column_count_mismatch",
                "severity": "warning",
                "message": f"Header has {header_cols} columns but data row has {data_cols}",
            }
        break
    return None


def _check_unclosed_tags(elem_id: int, html: str) -> dict | None:
    """Flag tables with unclosed HTML tags."""
    open_count = len(re.findall(r"<table", html, re.IGNORECASE))
    close_count = len(re.findall(r"</table>", html, re.IGNORECASE))
    if open_count > close_count:
        return {
            "element_id": elem_id,
            "check": "unclosed_html_tags",
            "severity": "warning",
            "message": f"Unclosed table tags: {open_count} opened, {close_count} closed",
        }
    return None


def _check_possible_checkbox(elem_id: int, content: str, bbox_list: list) -> dict | None:
    """Flag small empty/single-char text elements (likely checkboxes)."""
    if len(content.strip()) > 1:
        return None
    for bbox in bbox_list:
        coord = bbox.get("coord", [])
        if len(coord) >= 4:
            w = coord[2] - coord[0]
            h = coord[3] - coord[1]
            if w * h < 900 and w < 40 and h < 40:
                return {
                    "element_id": elem_id,
                    "check": "possible_checkbox",
                    "severity": "info",
                    "message": f"Small element ({w}x{h}px) with {'empty' if not content.strip() else 'single-char'} content — possible checkbox",
                }
    return None


def _check_reading_order(elements: list) -> list[dict]:
    """Flag elements where reading order appears wrong (Y jumps backward)."""
    flags = []
    # Group by page
    pages: dict[int, list] = {}
    for elem in elements:
        for bbox in elem.get("bbox", []):
            pid = bbox.get("page_id", 0)
            coord = bbox.get("coord", [])
            if len(coord) >= 4:
                pages.setdefault(pid, []).append((elem.get("id"), coord[1]))  # (elem_id, y1)
                break

    for pid, elems in pages.items():
        for i in range(1, len(elems)):
            prev_id, prev_y = elems[i - 1]
            curr_id, curr_y = elems[i]
            # If current element is significantly above previous (>200px jump back)
            if prev_y - curr_y > 200:
                flags.append({
                    "element_id": curr_id,
                    "check": "reading_order_anomaly",
                    "severity": "info",
                    "message": f"Element appears above previous element on page {pid + 1} (Y jumped from {prev_y} to {curr_y})",
                })
    return flags


def _check_mixed_scripts(elem_id: int, content: str) -> dict | None:
    """Flag content with unexpected mixed Unicode scripts."""
    if len(content) < 10:
        return None
    scripts: Counter = Counter()
    for char in content:
        if char.isalpha():
            try:
                script = unicodedata.name(char, "").split()[0]
                scripts[script] += 1
            except (ValueError, IndexError):
                pass

    # If we have 3+ distinct scripts with the minority being >5% of chars
    if len(scripts) >= 3:
        total = sum(scripts.values())
        minority_scripts = [s for s, c in scripts.items() if 0.02 < c / total < 0.3]
        if minority_scripts:
            return {
                "element_id": elem_id,
                "check": "mixed_unicode_scripts",
                "severity": "info",
                "message": f"Mixed scripts detected: {', '.join(scripts.keys())}",
            }
    return None


def _check_numeric_ocr(elem_id: int, content: str) -> dict | None:
    """Flag text that looks numeric but contains O (likely should be 0)."""
    # Look for patterns like "1O3.5" or "$1O,OOO" — O mixed with digits
    stripped = content.strip()
    if len(stripped) < 3:
        return None
    # Must have at least some digits
    digit_count = sum(1 for c in stripped if c.isdigit())
    if digit_count < 2:
        return None
    # Check for O (letter) surrounded by digits or in numeric context
    if re.search(r"\d[O]\d", stripped) or re.search(r"\d[O][O]", stripped):
        return {
            "element_id": elem_id,
            "check": "suspicious_numeric_ocr",
            "severity": "warning",
            "message": f"Letter 'O' found in numeric context (likely should be '0'): '{stripped[:50]}'",
        }
    return None
