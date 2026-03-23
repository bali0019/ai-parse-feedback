"""Export/Import endpoints: ZIP bundle, HTML report, JSONL manifest."""

import io
import json
import uuid
import time as _time
import zipfile
import html as html_lib
import logging
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from threading import Thread

import requests
from fastapi import APIRouter, HTTPException, UploadFile, File, BackgroundTasks
from fastapi.responses import StreamingResponse

from db import documents as docs_db
from db import feedback as feedback_db
from services.image_loader import get_page_elements
from utils.auth import get_databricks_token, get_workspace_url

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/export", tags=["export"])


# In-memory export job status store
_export_jobs: dict[str, dict] = {}


def _make_export_filename(doc_ids: list[str]) -> str:
    """Build export filename with use case prefix."""
    first_doc = docs_db.get_document(doc_ids[0]) if doc_ids else None
    use_case = first_doc.get("use_case_name", "").replace(" ", "_") if first_doc else ""
    prefix = f"{use_case}_" if use_case else ""
    date = datetime.now().strftime('%Y-%m-%d')

    if len(doc_ids) == 1 and first_doc:
        safe_name = first_doc["filename"].rsplit(".", 1)[0] if "." in first_doc["filename"] else first_doc["filename"]
        return f"{prefix}{safe_name}_feedback_{date}.zip"
    return f"{prefix}bulk_export_{date}.zip"


def _download_files_parallel(paths: list[str], token: str, max_workers: int = 20) -> dict[str, bytes]:
    """Download multiple files in parallel. Returns {path: bytes}."""
    results: dict[str, bytes] = {}

    def _dl(path):
        data = _download_file_from_volume(path, token)
        return path, data

    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        for path, data in pool.map(_dl, paths):
            if data:
                results[path] = data

    return results


def _download_file_from_volume(volume_path: str, token: str = None) -> bytes | None:
    """Download a file from UC Volume via Files API."""
    try:
        if not token:
            token = get_databricks_token()
        workspace_url = get_workspace_url()
        api_url = f"{workspace_url}/api/2.0/fs/files{volume_path}"
        resp = requests.get(api_url, headers={"Authorization": f"Bearer {token}"}, timeout=60)
        resp.raise_for_status()
        return resp.content
    except Exception as e:
        logger.warning(f"Could not download {volume_path}: {e}")
        return None


def _build_doc_zip_content(zf: zipfile.ZipFile, doc: dict, feedbacks: list, token: str, prefix: str = ""):
    """Add one document's content to a ZIP file. Shared by single and bulk export."""
    from services.image_loader import render_annotated_image

    parsed = doc.get("parsed_result", {})
    elements = parsed.get("document", {}).get("elements", [])
    elements_by_id = {e.get("id"): e for e in elements}
    pages = parsed.get("document", {}).get("pages", [])
    feedback_map = {f["element_id"]: f for f in feedbacks}

    # 1. Source PDF
    if doc.get("volume_path"):
        pdf_bytes = _download_file_from_volume(doc["volume_path"], token)
        if pdf_bytes:
            zf.writestr(f"{prefix}source/{doc['filename']}", pdf_bytes)

    # 2. ALL page images (required for bbox overlay on import)
    page_uris = []
    for i, page in enumerate(pages):
        uri = page.get("image_uri")
        if uri:
            page_uris.append(uri)

    page_image_bytes = _download_files_parallel(page_uris, token, max_workers=20)

    for i, page in enumerate(pages):
        uri = page.get("image_uri")
        if uri and uri in page_image_bytes:
            ext = uri.rsplit(".", 1)[-1] if "." in uri else "png"
            zf.writestr(f"{prefix}pages/page_{i}.{ext}", page_image_bytes[uri])

    # 3. Annotated issue images (for issues_report.html)
    issue_feedbacks = [f for f in feedbacks if f.get("is_correct") is False]
    for f in issue_feedbacks:
        pid = f.get("page_id", 0)
        if pid < len(pages):
            uri = pages[pid].get("image_uri")
            if uri and uri in page_image_bytes:
                elem = elements_by_id.get(f["element_id"], {})
                for bb in elem.get("bbox", []):
                    if bb.get("page_id") == pid and len(bb.get("coord", [])) >= 4:
                        annotated = render_annotated_image(
                            page_image_bytes[uri], bb["coord"],
                            color="#e74c3c",
                            label=f"{elem.get('type', '')} #{f['element_id']}"
                        )
                        zf.writestr(f"{prefix}issues/page_{pid + 1}_element_{f['element_id']}.png", annotated)
                        break

    # 3. Parsed result
    zf.writestr(f"{prefix}parsed_result.json", json.dumps(parsed, indent=2))

    # 4. Manifest
    manifest_lines = [json.dumps({
        "type": "metadata", "document_id": doc.get("document_id", ""),
        "filename": doc["filename"], "parse_version": "2.0",
        "page_count": len(pages), "element_count": len(elements),
        "use_case_name": doc.get("use_case_name"),
        "quality_flags": doc.get("quality_flags"),
        "exported_at": datetime.now(timezone.utc).isoformat(), "exporter": "ai-parse-feedback/1.0",
    })]
    for elem in elements:
        elem_id = elem.get("id")
        fb = feedback_map.get(elem_id)
        bbox_list = elem.get("bbox", [])
        manifest_lines.append(json.dumps({
            "type": "element", "element_id": elem_id,
            "page_id": bbox_list[0].get("page_id", 0) if bbox_list else 0,
            "element_type": elem.get("type"), "bbox": bbox_list[0].get("coord", []) if bbox_list else [],
            "content": elem.get("content", ""),
            "feedback": {
                "is_correct": fb.get("is_correct"), "issue_category": fb.get("issue_category"),
                "comment": fb.get("comment"), "suggested_content": fb.get("suggested_content"),
                "suggested_type": fb.get("suggested_type"),
            } if fb else None,
        }))
    correct = sum(1 for f in feedbacks if f.get("is_correct"))
    issues = sum(1 for f in feedbacks if f.get("is_correct") is False)
    issue_breakdown: dict[str, int] = {}
    for f in feedbacks:
        cat = f.get("issue_category")
        if cat and not f.get("is_correct"):
            issue_breakdown[cat] = issue_breakdown.get(cat, 0) + 1
    manifest_lines.append(json.dumps({
        "type": "summary", "total_pages": len(pages), "total_elements": len(elements),
        "elements_reviewed": len(feedbacks), "elements_correct": correct,
        "elements_with_issues": issues, "issue_breakdown": issue_breakdown,
    }))
    zf.writestr(f"{prefix}manifest.jsonl", "\n".join(manifest_lines))

    # 5. Self-contained issues_report.html (viewable without the app)
    if issue_feedbacks:
        issue_cards_html = []
        for f in issue_feedbacks:
            elem = elements_by_id.get(f["element_id"], {})
            pid = f.get("page_id", 0)
            cat = f.get("issue_category", "other")
            comment = html_lib.escape(f.get("comment") or "No comment")
            elem_type = html_lib.escape(f.get("element_type") or elem.get("type", ""))
            content_preview = html_lib.escape((elem.get("content") or elem.get("description") or "")[:300])
            img_file = f"issues/page_{pid + 1}_element_{f['element_id']}.png"
            suggested = html_lib.escape(f.get("suggested_content") or "")
            suggested_type = html_lib.escape(f.get("suggested_type") or "")

            corrections = ""
            if suggested:
                corrections += f'<p style="margin:4px 0;font-size:13px"><strong>Suggested content:</strong> {suggested}</p>'
            if suggested_type:
                corrections += f'<p style="margin:4px 0;font-size:13px"><strong>Suggested type:</strong> {suggested_type}</p>'

            issue_cards_html.append(f"""
            <div style="border:1px solid #e0e0e0;border-radius:8px;margin:16px 0;overflow:hidden">
                <div style="background:#f8f9fa;padding:10px 16px;border-bottom:1px solid #e0e0e0;display:flex;align-items:center;gap:12px">
                    <span style="background:#e74c3c20;color:#e74c3c;padding:3px 10px;border-radius:12px;font-size:12px;font-weight:600">{html_lib.escape(cat.replace('_',' '))}</span>
                    <span style="font-size:12px;color:#666">Element #{f['element_id']} &middot; {elem_type} &middot; Page {pid + 1}</span>
                </div>
                <div style="padding:16px">
                    <img src="{img_file}" style="max-width:100%;border:1px solid #ddd;border-radius:4px" />
                    <p style="margin:12px 0 4px;font-size:14px"><strong>Feedback:</strong> {comment}</p>
                    {corrections}
                    {f'<p style="margin:4px 0;font-size:12px;color:#666;background:#f8f8f8;padding:8px;border-radius:4px"><strong>Parsed content:</strong> {content_preview}{"..." if len(content_preview) >= 300 else ""}</p>' if content_preview else ''}
                </div>
            </div>""")

        breakdown_li = "".join(f"<li><strong>{c.replace('_',' ').title()}</strong>: {n}</li>"
                               for c, n in sorted(issue_breakdown.items(), key=lambda x: -x[1]))

        report_html = f"""<!DOCTYPE html>
<html><head><meta charset="UTF-8"><title>Issues Report - {html_lib.escape(doc['filename'])}</title>
<style>body{{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;max-width:900px;margin:0 auto;padding:30px 20px;color:#333}}
h1{{color:#1a1a2e;border-bottom:3px solid #e74c3c;padding-bottom:10px}}
.stats{{display:flex;gap:12px;margin:12px 0;flex-wrap:wrap}}
.s{{background:#f0f0f0;padding:6px 14px;border-radius:6px;font-size:13px}}
.s.ok{{background:#d4edda;color:#155724}}.s.bad{{background:#f8d7da;color:#721c24}}
@media print{{body{{padding:10px}}div[style*="border:1px"]{{page-break-inside:avoid}}}}</style>
</head><body>
<h1>Issues Report: {html_lib.escape(doc['filename'])}</h1>
<div class="stats">
<div class="s"><strong>{len(pages)}</strong> pages</div>
<div class="s"><strong>{len(elements)}</strong> elements</div>
<div class="s"><strong>{len(feedbacks)}</strong> reviewed</div>
<div class="s ok"><strong>{correct}</strong> correct</div>
<div class="s bad"><strong>{issues}</strong> issues</div>
</div>
{f'<h3>Issue Breakdown</h3><ul>{breakdown_li}</ul>' if breakdown_li else ''}
<h2>Issues ({len(issue_feedbacks)})</h2>
{''.join(issue_cards_html)}
<p style="color:#999;font-size:11px;margin-top:30px;border-top:1px solid #eee;padding-top:10px">
Generated by AI Parse Feedback on {datetime.now().strftime('%Y-%m-%d %H:%M UTC')}</p>
</body></html>"""
        zf.writestr(f"{prefix}issues_report.html", report_html)

    return {"correct": correct, "issues": issues, "elements": len(elements), "reviewed": len(feedbacks)}


def _run_export_job(export_id: str, doc_ids: list[str]):
    """Background job: build ZIP and store in memory."""
    try:
        _export_jobs[export_id] = {"status": "processing", "progress": "Starting..."}
        token = get_databricks_token()

        buf = io.BytesIO()
        aggregate_stats = {"total_documents": len(doc_ids), "documents": []}

        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            for i, doc_id in enumerate(doc_ids):
                doc = docs_db.get_document(doc_id)
                if not doc or not doc.get("parsed_result"):
                    continue

                _export_jobs[export_id]["progress"] = f"Exporting {doc['filename']} ({i + 1}/{len(doc_ids)})..."

                feedbacks = feedback_db.get_feedback_for_document(doc_id)
                prefix = f"{doc['filename'].rsplit('.', 1)[0]}/" if len(doc_ids) > 1 else ""
                stats = _build_doc_zip_content(zf, doc, feedbacks, token, prefix=prefix)
                aggregate_stats["documents"].append({"document_id": doc_id, "filename": doc["filename"], **stats})

            if len(doc_ids) > 1:
                zf.writestr("summary.json", json.dumps(aggregate_stats, indent=2))

        _export_jobs[export_id] = {
            "status": "ready",
            "zip_bytes": buf.getvalue(),
            "filename": _make_export_filename(doc_ids),
        }
        logger.info(f"Export {export_id} complete: {len(buf.getvalue())} bytes")

    except Exception as e:
        logger.error(f"Export {export_id} failed: {e}", exc_info=True)
        _export_jobs[export_id] = {"status": "error", "error": str(e)}


@router.post("/start")
def start_export(body: dict):
    """Start export — inline for small docs, serverless job for large ones."""
    from config import EXPORT_JOB_ID, EXPORT_JOB_PAGE_THRESHOLD, IMAGE_OUTPUT_VOLUME_PATH

    doc_ids = body.get("document_ids", [])
    if not doc_ids:
        raise HTTPException(400, "No document IDs provided")

    # Calculate total pages to decide inline vs job
    total_pages = 0
    for doc_id in doc_ids:
        doc = docs_db.get_document(doc_id)
        if doc:
            total_pages += doc.get("page_count") or 0

    # Use serverless job for large exports
    if EXPORT_JOB_ID and total_pages > EXPORT_JOB_PAGE_THRESHOLD:
        from databricks.sdk import WorkspaceClient
        w = WorkspaceClient()

        output_path = f"{IMAGE_OUTPUT_VOLUME_PATH}/_exports/{uuid.uuid4()}.zip"
        run = w.jobs.run_now(
            job_id=int(EXPORT_JOB_ID),
            job_parameters={
                "action": "export",
                "document_ids": ",".join(doc_ids),
                "output_path": output_path,
                "input_path": "",
                "lakebase_instance": "ai-parse-feedback-db",
            }
        )

        run_id = str(run.run_id)
        _export_jobs[run_id] = {"status": "job", "output_path": output_path, "mode": "job", "type": "export", "doc_ids": doc_ids, "created_at": _time.time()}
        logger.info(f"Export delegated to job: run_id={run_id}, total_pages={total_pages}")

        return {"export_id": run_id, "status": "processing", "mode": "job", "total_pages": total_pages}

    # Inline for small exports
    export_id = str(uuid.uuid4())
    _export_jobs[export_id] = {"status": "processing", "progress": "Starting...", "mode": "inline", "type": "export", "created_at": _time.time()}

    thread = Thread(target=_run_export_job, args=(export_id, doc_ids), daemon=True)
    thread.start()

    return {"export_id": export_id, "status": "processing", "mode": "inline", "total_pages": total_pages}


@router.get("/status/{export_id}")
def get_export_status(export_id: str):
    """Check export status — handles both inline and job modes."""
    job = _export_jobs.get(export_id)
    if not job:
        raise HTTPException(404, "Export job not found")

    mode = job.get("mode", "inline")

    if mode == "job":
        # Poll the Databricks job
        from databricks.sdk import WorkspaceClient
        w = WorkspaceClient()
        try:
            run = w.jobs.get_run(int(export_id))
            state = run.state
            lcs = state.life_cycle_state.value if state.life_cycle_state else "UNKNOWN"
            rs = state.result_state.value if state.result_state else None

            if lcs in ("TERMINATED", "SKIPPED", "INTERNAL_ERROR"):
                if rs == "SUCCESS":
                    return {"status": "ready", "mode": "job", "filename": _make_export_filename(job.get("doc_ids", []))}
                else:
                    return {"status": "error", "mode": "job", "error": state.state_message or "Job failed"}
            else:
                return {"status": "processing", "mode": "job", "progress": f"Job state: {lcs}"}
        except Exception as e:
            return {"status": "error", "mode": "job", "error": str(e)}

    # Inline mode
    return {
        "status": job["status"],
        "mode": "inline",
        "progress": job.get("progress"),
        "error": job.get("error"),
        "filename": job.get("filename"),
    }


@router.get("/active-jobs")
def get_active_jobs():
    """Return all active import/export jobs for the global status bar."""
    now = _time.time()
    active = []
    to_delete = []

    for job_id, job in list(_export_jobs.items()):
        status = job.get("status", "unknown")
        created = job.get("created_at", 0)

        # Clean up anything that's not actively processing
        if status not in ("processing", "job"):
            to_delete.append(job_id)
            continue

        # Clean up stale inline entries (>10 min)
        if job.get("mode") == "inline" and created > 0 and (now - created) > 600:
            to_delete.append(job_id)
            continue

        # Clean up stale job entries (>1 hour)
        if job.get("mode") == "job" and created > 0 and (now - created) > 3600:
            to_delete.append(job_id)
            continue

        active.append({
            "id": job_id,
            "mode": job.get("mode", "inline"),
            "status": "processing",
            "progress": job.get("progress", ""),
            "type": job.get("type", "export"),
            "filename": job.get("filename", ""),
        })

    for job_id in to_delete:
        _export_jobs.pop(job_id, None)

    return active


@router.delete("/clear-jobs")
def clear_all_jobs():
    """Debug: clear all active job entries."""
    count = len(_export_jobs)
    _export_jobs.clear()
    return {"cleared": count}


@router.get("/download/{export_id}")
def download_export(export_id: str):
    """Download completed export ZIP — from memory (inline) or UC Volume (job)."""
    job = _export_jobs.get(export_id)
    if not job:
        raise HTTPException(404, "Export job not found")

    mode = job.get("mode", "inline")

    if mode == "job":
        # Download from UC Volume where the job wrote the ZIP
        output_path = job.get("output_path")
        if not output_path:
            raise HTTPException(500, "No output path for job export")

        zip_bytes = _download_file_from_volume(output_path)
        if not zip_bytes:
            raise HTTPException(500, "Could not download export ZIP from volume")

        filename = _make_export_filename(job.get("doc_ids", []))
        del _export_jobs[export_id]

        return StreamingResponse(
            io.BytesIO(zip_bytes),
            media_type="application/zip",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )

    # Inline mode
    if job["status"] != "ready":
        raise HTTPException(400, f"Export not ready: {job['status']}")

    zip_bytes = job["zip_bytes"]
    filename = job["filename"]

    del _export_jobs[export_id]

    return StreamingResponse(
        io.BytesIO(zip_bytes),
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# Keep the old GET endpoint for backward compat (small docs, inline)
@router.get("/document/{document_id}")
def export_document(document_id: str):
    """Export document inline (for small docs). Use /start for large docs."""
    doc = docs_db.get_document(document_id)
    if not doc:
        raise HTTPException(404, "Document not found")
    if not doc.get("parsed_result"):
        raise HTTPException(400, "Document not parsed yet")

    feedbacks = feedback_db.get_feedback_for_document(document_id)
    token = get_databricks_token()

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        _build_doc_zip_content(zf, doc, feedbacks, token)

    buf.seek(0)
    zip_name = _make_export_filename([document_id])

    return StreamingResponse(
        buf,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{zip_name}"'},
    )


@router.post("/bulk")
def bulk_export(body: dict):
    """Start a background bulk export. Same as /start."""
    return start_export(body)


def _build_report_html(documents_data: list[dict]) -> str:
    """Build a print-friendly HTML report with page images and bbox overlays."""
    from services.image_loader import load_page_image

    # Pre-fetch one token for all image downloads
    token = get_databricks_token()

    issue_colors = {
        "wrong_element_type": "#e74c3c", "incorrect_boundaries": "#e67e22",
        "missing_content": "#f39c12", "merged_elements": "#9b59b6",
        "split_elements": "#8e44ad", "duplicate_content": "#2ecc71",
        "ocr_error": "#e74c3c", "table_structure_error": "#3498db",
        "checkbox_not_recognized": "#1abc9c", "chart_data_not_extracted": "#f39c12",
        "generic_image_placeholder": "#95a5a6", "content_truncated": "#e67e22",
        "wrong_reading_order": "#9b59b6", "header_footer_misclassified": "#34495e",
        "other": "#95a5a6",
    }

    MAX_IMG_WIDTH = 600

    doc_sections = []
    total_elements = 0
    total_reviewed = 0
    total_correct = 0
    total_issues = 0
    all_issue_breakdown: dict[str, int] = {}

    for doc_data in documents_data:
        doc = doc_data["doc"]
        feedbacks = doc_data["feedbacks"]
        parsed = doc.get("parsed_result", {})
        elements = parsed.get("document", {}).get("elements", [])
        elements_by_id = {e.get("id"): e for e in elements}
        pages = parsed.get("document", {}).get("pages", [])

        correct = sum(1 for f in feedbacks if f.get("is_correct"))
        issues_count = sum(1 for f in feedbacks if f.get("is_correct") is False)
        total_elements += len(elements)
        total_reviewed += len(feedbacks)
        total_correct += correct
        total_issues += issues_count

        # Collect issue feedbacks and group by page
        issue_feedbacks = [f for f in feedbacks if f.get("is_correct") is False]
        pages_with_issues: dict[int, list] = {}
        for f in issue_feedbacks:
            pid = f.get("page_id", 0)
            pages_with_issues.setdefault(pid, []).append(f)
            cat = f.get("issue_category", "other")
            all_issue_breakdown[cat] = all_issue_breakdown.get(cat, 0) + 1

        # Pre-load all issue page images in parallel
        page_uris = {}
        for pid in pages_with_issues:
            if pid < len(pages):
                uri = pages[pid].get("image_uri")
                if uri:
                    page_uris[pid] = uri

        page_image_cache: dict[int, dict | None] = {}

        def _load_img(pid_uri):
            pid, uri = pid_uri
            return pid, load_page_image(uri, token=token)

        with ThreadPoolExecutor(max_workers=10) as pool:
            for pid, img_data in pool.map(_load_img, page_uris.items()):
                page_image_cache[pid] = img_data

        # Build issue cards with page images + bbox overlays
        issue_cards = []
        for page_id in sorted(pages_with_issues.keys()):
            page_feedbacks = pages_with_issues[page_id]
            img = page_image_cache.get(page_id)

            for f in page_feedbacks:
                elem = elements_by_id.get(f["element_id"], {})
                cat = f.get("issue_category", "other")
                color = issue_colors.get(cat, "#95a5a6")
                comment = html_lib.escape(f.get("comment") or "No comment")
                elem_type = html_lib.escape(f.get("element_type") or elem.get("type", ""))
                content_preview = html_lib.escape((elem.get("content") or elem.get("description") or "")[:200])

                # Build image with bbox overlay
                img_html = '<div style="background:#f0f0f0;height:100px;display:flex;align-items:center;justify-content:center;color:#999;border-radius:4px">No image available</div>'
                if img:
                    orig_w = img["width"]
                    orig_h = img["height"]
                    scale = min(1.0, MAX_IMG_WIDTH / orig_w)
                    disp_w = int(orig_w * scale)
                    disp_h = int(orig_h * scale)

                    # Find bbox for this element on this page
                    bbox_overlay = ""
                    for bbox in elem.get("bbox", []):
                        if bbox.get("page_id") == page_id and len(bbox.get("coord", [])) >= 4:
                            x1, y1, x2, y2 = bbox["coord"]
                            bx = x1 * scale
                            by = y1 * scale
                            bw = (x2 - x1) * scale
                            bh = (y2 - y1) * scale
                            bbox_overlay = f'''<div style="position:absolute;left:{bx:.0f}px;top:{by:.0f}px;width:{bw:.0f}px;height:{bh:.0f}px;border:3px solid {color};background:{color}22;box-sizing:border-box;"></div>
                            <div style="position:absolute;left:{bx:.0f}px;top:{max(0, by - 18):.0f}px;background:{color};color:white;font-size:10px;padding:1px 6px;border-radius:2px;font-weight:bold">{elem_type.upper()} #{f['element_id']}</div>'''

                    img_html = f'''<div style="position:relative;display:inline-block;border:1px solid #ddd;border-radius:4px;overflow:hidden">
                        <img src="{img['data_uri']}" style="display:block;width:{disp_w}px;height:{disp_h}px" />
                        {bbox_overlay}
                    </div>'''

                issue_cards.append(f"""
                <div class="issue-card">
                    <div class="issue-header">
                        <span class="issue-badge" style="background:{color}20;color:{color}">
                            {html_lib.escape(cat.replace('_', ' '))}
                        </span>
                        <span class="issue-meta">Element #{f['element_id']} &middot; {elem_type} &middot; Page {page_id + 1}</span>
                    </div>
                    <div class="issue-body">
                        <div class="issue-image">{img_html}</div>
                        <div class="issue-details">
                            <p class="issue-comment">{comment}</p>
                            {f'<p class="issue-content"><strong>Parsed content:</strong> {content_preview}{"..." if len(content_preview) >= 200 else ""}</p>' if content_preview else ''}
                        </div>
                    </div>
                </div>""")

        issues_section = ""
        if issue_cards:
            issues_section = f"""<h3>Issues Found ({len(issue_cards)})</h3>{''.join(issue_cards)}"""

        doc_sections.append(f"""
        <div class="doc-section">
            <h2>{html_lib.escape(doc['filename'])}</h2>
            <div class="stats-row">
                <div class="stat"><strong>{len(pages)}</strong> pages</div>
                <div class="stat"><strong>{len(elements)}</strong> elements</div>
                <div class="stat"><strong>{len(feedbacks)}</strong> reviewed</div>
                <div class="stat correct"><strong>{correct}</strong> correct</div>
                <div class="stat issue"><strong>{issues_count}</strong> issues</div>
            </div>
            {issues_section}
        </div>""")

    breakdown_items = "".join(
        f'<li><strong>{cat.replace("_", " ").title()}</strong>: {count}</li>'
        for cat, count in sorted(all_issue_breakdown.items(), key=lambda x: -x[1])
    )

    return f"""<!DOCTYPE html>
<html><head>
<meta charset="UTF-8">
<title>AI Parse Feedback Report</title>
<style>
    body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; max-width: 960px; margin: 0 auto; padding: 40px 20px; color: #333; }}
    h1 {{ color: #1a1a2e; border-bottom: 3px solid #2563eb; padding-bottom: 10px; }}
    h2 {{ color: #2563eb; margin-top: 40px; }}
    h3 {{ color: #555; margin-top: 24px; }}
    .summary {{ background: #f8f9fa; border-radius: 8px; padding: 20px; margin: 20px 0; }}
    .stats-row {{ display: flex; gap: 16px; margin: 12px 0; flex-wrap: wrap; }}
    .stat {{ background: #f0f0f0; padding: 8px 16px; border-radius: 6px; font-size: 14px; }}
    .stat.correct {{ background: #d4edda; color: #155724; }}
    .stat.issue {{ background: #f8d7da; color: #721c24; }}
    .doc-section {{ margin-bottom: 40px; }}
    .issue-card {{ border: 1px solid #e0e0e0; border-radius: 8px; margin: 16px 0; overflow: hidden; }}
    .issue-header {{ background: #f8f9fa; padding: 10px 16px; border-bottom: 1px solid #e0e0e0; display: flex; align-items: center; gap: 12px; }}
    .issue-badge {{ padding: 3px 10px; border-radius: 12px; font-size: 12px; font-weight: 600; }}
    .issue-meta {{ font-size: 12px; color: #666; }}
    .issue-body {{ padding: 16px; }}
    .issue-image {{ margin-bottom: 12px; }}
    .issue-comment {{ font-size: 14px; color: #333; margin: 8px 0; }}
    .issue-content {{ font-size: 12px; color: #666; margin: 4px 0; background: #f8f8f8; padding: 8px; border-radius: 4px; word-break: break-word; }}
    .generated {{ color: #999; font-size: 12px; margin-top: 40px; padding-top: 20px; border-top: 1px solid #eee; }}
    @media print {{
        body {{ padding: 20px; }}
        .issue-card {{ page-break-inside: avoid; }}
        h2 {{ page-break-before: always; }}
        h2:first-of-type {{ page-break-before: auto; }}
    }}
</style>
</head><body>
<h1>AI Parse Feedback Report</h1>
<div class="summary">
    <strong>Summary:</strong> {len(documents_data)} document(s) | {total_elements} elements | {total_reviewed} reviewed | {total_correct} correct | {total_issues} issues
    {f'<ul>{breakdown_items}</ul>' if breakdown_items else ''}
</div>
{''.join(doc_sections)}
<p class="generated">Generated by AI Parse Feedback on {datetime.now().strftime('%Y-%m-%d %H:%M UTC')}</p>
</body></html>"""


@router.get("/report/{document_id}")
def export_report(document_id: str):
    """Generate an HTML report for a single document."""
    from fastapi.responses import HTMLResponse
    doc = docs_db.get_document(document_id)
    if not doc:
        raise HTTPException(404, "Document not found")
    feedbacks = feedback_db.get_feedback_for_document(document_id)
    html = _build_report_html([{"doc": doc, "feedbacks": feedbacks}])
    return HTMLResponse(content=html)


@router.post("/bulk-report")
def export_bulk_report(body: dict):
    """Generate an HTML report for multiple documents."""
    from fastapi.responses import HTMLResponse
    doc_ids = body.get("document_ids", [])
    if not doc_ids:
        raise HTTPException(400, "No document IDs provided")

    documents_data = []
    for doc_id in doc_ids:
        doc = docs_db.get_document(doc_id)
        if doc and doc.get("parsed_result"):
            feedbacks = feedback_db.get_feedback_for_document(doc_id)
            documents_data.append({"doc": doc, "feedbacks": feedbacks})

    html = _build_report_html(documents_data)
    return HTMLResponse(content=html)


def _import_single_doc(zf: zipfile.ZipFile, manifest_path: str) -> dict:
    """Import a single document from a manifest.jsonl path within a ZIP."""
    dir_prefix = manifest_path.rsplit("manifest.jsonl", 1)[0]  # e.g. "bulk/doc1/" or ""

    manifest_text = zf.read(manifest_path).decode("utf-8")
    lines = [json.loads(line) for line in manifest_text.strip().split("\n") if line.strip()]

    metadata = next((l for l in lines if l.get("type") == "metadata"), None)
    if not metadata:
        return {"status": "error", "error": f"No metadata in {manifest_path}"}

    # Find parsed_result.json relative to this manifest
    parsed_path = f"{dir_prefix}parsed_result.json"
    parsed_result = None
    if parsed_path in zf.namelist():
        parsed_result = json.loads(zf.read(parsed_path).decode("utf-8"))

    # Upload source PDF and page images to UC Volume
    from config import VOLUME_CONFIG, IMAGE_OUTPUT_VOLUME_PATH
    from services.ingest import upload_to_volume
    from utils.auth import get_databricks_token as _get_token, get_workspace_url as _get_url

    volume_path = None
    import_doc_id = str(uuid.uuid4())  # pre-generate for image path

    source_files = [n for n in zf.namelist() if n.startswith(dir_prefix + "source/") and not n.endswith("/") and "__MACOSX" not in n]
    if source_files and VOLUME_CONFIG:
        try:
            pdf_bytes = zf.read(source_files[0])
            result = upload_to_volume(
                pdf_bytes, metadata["filename"],
                VOLUME_CONFIG["catalog"], VOLUME_CONFIG["schema"], VOLUME_CONFIG["volume_name"],
            )
            volume_path = result["volume_path"]
        except Exception as e:
            logger.warning(f"Could not upload imported PDF to volume: {e}")

    # Upload page images and update image_uri in parsed_result
    image_output_path = None
    if parsed_result and IMAGE_OUTPUT_VOLUME_PATH:
        pages_in_parsed = parsed_result.get("document", {}).get("pages", [])
        page_files = [n for n in zf.namelist()
                      if n.startswith(dir_prefix + "pages/") and not n.endswith("/") and "__MACOSX" not in n]

        if page_files:
            image_output_path = f"{IMAGE_OUTPUT_VOLUME_PATH}/{import_doc_id}/"
            token = _get_token()
            url = _get_url()

            # Upload page images in parallel
            def _upload_page(pf):
                try:
                    img_bytes = zf.read(pf)
                    fname = pf.rsplit("/", 1)[-1]
                    page_idx_str = fname.replace("page_", "").rsplit(".", 1)[0]
                    page_idx = int(page_idx_str)
                    dest_path = f"{image_output_path}{fname}"
                    api_url = f"{url}/api/2.0/fs/files{dest_path}"
                    resp = requests.put(api_url, data=img_bytes,
                                        headers={"Authorization": f"Bearer {token}"},
                                        params={"overwrite": "true"})
                    if resp.status_code in (200, 201, 204):
                        return page_idx, dest_path
                except Exception as e:
                    logger.warning(f"Could not upload page image {pf}: {e}")
                return None, None

            with ThreadPoolExecutor(max_workers=20) as pool:
                for page_idx, dest_path in pool.map(_upload_page, page_files):
                    if page_idx is not None and dest_path and page_idx < len(pages_in_parsed):
                        pages_in_parsed[page_idx]["image_uri"] = dest_path

    # Create document record
    doc_id = docs_db.insert_document(
        filename=metadata["filename"],
        volume_path=volume_path,
        use_case_name=metadata.get("use_case_name") or metadata.get("customer_name"),
    )

    if parsed_result:
        docs_db.update_document_status(
            doc_id,
            status="parsed",
            parsed_result=parsed_result,
            image_output_path=image_output_path,
            page_count=metadata.get("page_count"),
            element_count=metadata.get("element_count"),
            quality_flags=metadata.get("quality_flags"),
        )

    # Import feedback using bulk upsert for speed
    element_lines = [l for l in lines if l.get("type") == "element" and l.get("feedback")]
    if element_lines:
        items = []
        for elem in element_lines:
            fb = elem["feedback"]
            if fb:
                items.append({
                    "element_id": elem["element_id"],
                    "page_id": elem["page_id"],
                    "element_type": elem.get("element_type"),
                    "bbox_coords": elem.get("bbox"),
                    "is_correct": fb.get("is_correct"),
                    "issue_category": fb.get("issue_category"),
                    "comment": fb.get("comment"),
                })
        if items:
            feedback_db.bulk_upsert_feedback(doc_id, items)

    return {
        "document_id": doc_id,
        "filename": metadata["filename"],
        "feedback_imported": len(element_lines),
        "status": "imported",
    }


def _run_import_inline(import_id: str, content: bytes):
    """Background thread: run import inline."""
    try:
        _export_jobs[import_id]["progress"] = "Reading ZIP..."
        buf = io.BytesIO(content)

        with zipfile.ZipFile(buf, "r") as zf:
            manifests = [n for n in zf.namelist() if n.endswith("manifest.jsonl") and "__MACOSX" not in n]

            results = []
            for i, manifest_path in enumerate(manifests):
                _export_jobs[import_id]["progress"] = f"Importing document {i + 1}/{len(manifests)} (uploading page images)..."
                result = _import_single_doc(zf, manifest_path)
                results.append(result)
                _export_jobs[import_id]["progress"] = f"Imported {i + 1}/{len(manifests)} documents"

            total_feedback = sum(r.get("feedback_imported", 0) for r in results)

        _export_jobs[import_id] = {
            "status": "ready", "mode": "inline",
            "documents_imported": len(results),
            "total_feedback_imported": total_feedback,
        }
        logger.info(f"Import {import_id} complete: {len(results)} docs, {total_feedback} feedback")

    except Exception as e:
        logger.error(f"Import {import_id} failed: {e}", exc_info=True)
        _export_jobs[import_id] = {"status": "error", "mode": "inline", "error": str(e)}

    logger.info(f"Import thread {import_id} final status: {_export_jobs.get(import_id, {}).get('status', 'unknown')}")


@router.post("/import")
async def import_document(file: UploadFile = File(...)):
    """Import a ZIP bundle — always async (inline thread or serverless job)."""
    from config import EXPORT_JOB_ID, IMPORT_SIZE_THRESHOLD_MB, IMAGE_OUTPUT_VOLUME_PATH

    content = await file.read()
    if not content:
        raise HTTPException(400, "Empty file")

    size_mb = len(content) / (1024 * 1024)
    import_id = str(uuid.uuid4())

    # Large ZIP → delegate to serverless job
    if EXPORT_JOB_ID and size_mb > IMPORT_SIZE_THRESHOLD_MB:
        from databricks.sdk import WorkspaceClient
        w = WorkspaceClient()

        # Upload ZIP to UC Volume
        input_path = f"{IMAGE_OUTPUT_VOLUME_PATH}/_imports/{import_id}.zip"
        token = get_databricks_token()
        workspace_url = get_workspace_url()
        resp = requests.put(
            f"{workspace_url}/api/2.0/fs/files{input_path}",
            data=content,
            headers={"Authorization": f"Bearer {token}"},
            params={"overwrite": "true"},
        )
        if resp.status_code not in (200, 201, 204):
            raise HTTPException(500, f"Failed to upload ZIP to volume: {resp.status_code}")

        run = w.jobs.run_now(
            job_id=int(EXPORT_JOB_ID),
            job_parameters={
                "action": "import",
                "document_ids": "",
                "input_path": input_path,
                "output_path": "",
                "lakebase_instance": "ai-parse-feedback-db",
            }
        )

        run_id = str(run.run_id)
        _export_jobs[run_id] = {"status": "processing", "mode": "job", "type": "import", "filename": file.filename, "created_at": _time.time()}
        logger.info(f"Import delegated to job: run_id={run_id}, size={size_mb:.1f}MB")

        return {"import_id": run_id, "status": "processing", "mode": "job", "size_mb": round(size_mb, 1)}

    # Small ZIP → inline background thread
    _export_jobs[import_id] = {"status": "processing", "mode": "inline", "type": "import", "filename": file.filename, "progress": "Starting...", "created_at": _time.time()}
    thread = Thread(target=_run_import_inline, args=(import_id, content), daemon=True)
    thread.start()

    return {"import_id": import_id, "status": "processing", "mode": "inline", "size_mb": round(size_mb, 1)}


@router.get("/import-status/{import_id}")
def get_import_status(import_id: str):
    """Check import status — handles both inline and job modes."""
    job = _export_jobs.get(import_id)
    if not job:
        raise HTTPException(404, "Import job not found")

    mode = job.get("mode", "inline")

    if mode == "job":
        from databricks.sdk import WorkspaceClient
        w = WorkspaceClient()
        try:
            run = w.jobs.get_run(int(import_id))
            state = run.state
            lcs = state.life_cycle_state.value if state.life_cycle_state else "UNKNOWN"
            rs = state.result_state.value if state.result_state else None

            if lcs in ("TERMINATED", "SKIPPED", "INTERNAL_ERROR"):
                if rs == "SUCCESS":
                    del _export_jobs[import_id]
                    return {"status": "ready", "mode": "job"}
                else:
                    del _export_jobs[import_id]
                    return {"status": "error", "mode": "job", "error": state.state_message or "Job failed"}
            else:
                return {"status": "processing", "mode": "job", "progress": f"Job state: {lcs}"}
        except Exception as e:
            return {"status": "error", "mode": "job", "error": str(e)}

    # Inline mode
    result = {
        "status": job["status"],
        "mode": "inline",
        "progress": job.get("progress"),
        "error": job.get("error"),
        "documents_imported": job.get("documents_imported"),
        "total_feedback_imported": job.get("total_feedback_imported"),
    }
    if job["status"] in ("ready", "error"):
        del _export_jobs[import_id]
    return result
