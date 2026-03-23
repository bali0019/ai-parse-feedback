"""Document API endpoints: upload, parse, list, get, page image."""

import os
import logging
from typing import Optional

from fastapi import APIRouter, UploadFile, File, Form, HTTPException, BackgroundTasks, Query

from config import VOLUME_CONFIG, IMAGE_OUTPUT_VOLUME_PATH, ISSUE_CATEGORIES, ELEMENT_COLORS
from db import documents as docs_db
from db import feedback as feedback_db
from services.ingest import upload_to_volume
from services.parse import parse_document
from services.image_loader import load_page_image, get_page_elements

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/documents", tags=["documents"])


@router.get("")
def list_documents(limit: int = Query(100, le=500), use_case: str = Query(None)):
    """List documents with feedback stats, optionally filtered by use case."""
    if use_case:
        docs = docs_db.list_documents_by_use_case(use_case, limit=limit)
    else:
        docs = docs_db.list_documents(limit=limit)
    for doc in docs:
        stats = docs_db.get_document_feedback_stats(doc["document_id"])
        doc["feedback_stats"] = stats
    return docs


@router.get("/use-cases")
def list_use_cases():
    """List distinct use cases with doc counts and issue stats."""
    return docs_db.list_use_cases()


@router.get("/analytics")
def get_analytics(use_case: str = Query(None)):
    """Get aggregated issue analytics, optionally filtered by use case."""
    from db.connection import get_cursor
    with get_cursor() as cur:
        if use_case and use_case != "All":
            if use_case == "Unassigned":
                cur.execute("""
                    SELECT f.issue_category, COUNT(*) as count
                    FROM feedback f JOIN documents d ON f.document_id = d.document_id
                    WHERE f.is_correct = false AND d.use_case_name IS NULL
                    GROUP BY f.issue_category ORDER BY count DESC
                """)
            else:
                cur.execute("""
                    SELECT f.issue_category, COUNT(*) as count
                    FROM feedback f JOIN documents d ON f.document_id = d.document_id
                    WHERE f.is_correct = false AND d.use_case_name = %s
                    GROUP BY f.issue_category ORDER BY count DESC
                """, (use_case,))
        else:
            cur.execute("""
                SELECT issue_category, COUNT(*) as count
                FROM feedback WHERE is_correct = false
                GROUP BY issue_category ORDER BY count DESC
            """)
        issue_breakdown = [dict(r) for r in cur.fetchall()]

    # Doc stats (separate query to avoid cross-product)
    with get_cursor() as cur:
        if use_case and use_case != "All":
            where = "WHERE use_case_name IS NULL" if use_case == "Unassigned" else "WHERE use_case_name = %s"
            params = () if use_case == "Unassigned" else (use_case,)
            cur.execute(f"SELECT COUNT(*) as total_docs, COALESCE(SUM(element_count), 0) as total_elements FROM documents {where}", params)
        else:
            cur.execute("SELECT COUNT(*) as total_docs, COALESCE(SUM(element_count), 0) as total_elements FROM documents")
        doc_stats = dict(cur.fetchone())

    # Feedback stats (separate query)
    with get_cursor() as cur:
        if use_case and use_case != "All":
            if use_case == "Unassigned":
                cur.execute("""
                    SELECT COUNT(*) as total_reviewed,
                           COUNT(*) FILTER (WHERE f.is_correct = true) as total_correct,
                           COUNT(*) FILTER (WHERE f.is_correct = false) as total_issues
                    FROM feedback f JOIN documents d ON f.document_id = d.document_id
                    WHERE d.use_case_name IS NULL
                """)
            else:
                cur.execute("""
                    SELECT COUNT(*) as total_reviewed,
                           COUNT(*) FILTER (WHERE f.is_correct = true) as total_correct,
                           COUNT(*) FILTER (WHERE f.is_correct = false) as total_issues
                    FROM feedback f JOIN documents d ON f.document_id = d.document_id
                    WHERE d.use_case_name = %s
                """, (use_case,))
        else:
            cur.execute("""
                SELECT COUNT(*) as total_reviewed,
                       COUNT(*) FILTER (WHERE is_correct = true) as total_correct,
                       COUNT(*) FILTER (WHERE is_correct = false) as total_issues
                FROM feedback
            """)
        fb_stats = dict(cur.fetchone())

    summary = {**doc_stats, **fb_stats}
    return {"issue_breakdown": issue_breakdown, "summary": summary}


@router.get("/config")
def get_config():
    """Return issue categories and element colors for the frontend."""
    return {
        "issue_categories": ISSUE_CATEGORIES,
        "element_colors": ELEMENT_COLORS,
    }


@router.post("/upload")
async def upload_document(file: UploadFile = File(...), use_case_name: str = Form(None)):
    """Upload a document to UC Volume and create a database record."""
    logger.info(f"Upload request: file={file.filename}, use_case_name='{use_case_name}' (type={type(use_case_name).__name__})")

    if not VOLUME_CONFIG:
        raise HTTPException(500, "VOLUME_PATH not configured")

    file_bytes = await file.read()
    if not file_bytes:
        raise HTTPException(400, "Empty file")

    # Upload to UC Volume
    result = upload_to_volume(
        file_bytes=file_bytes,
        filename=file.filename,
        catalog=VOLUME_CONFIG["catalog"],
        schema=VOLUME_CONFIG["schema"],
        volume_name=VOLUME_CONFIG["volume_name"],
    )

    # Insert document record
    doc_id = docs_db.insert_document(
        filename=file.filename,
        use_case_name=use_case_name,
        volume_path=result["volume_path"],
    )

    return {
        "document_id": doc_id,
        "filename": file.filename,
        "volume_path": result["volume_path"],
        "size_bytes": result["size_bytes"],
        "status": "uploaded",
    }


@router.post("/{document_id}/parse")
def trigger_parse(document_id: str, background_tasks: BackgroundTasks):
    """Trigger ai_parse_document for an uploaded document."""
    doc = docs_db.get_document(document_id)
    if not doc:
        raise HTTPException(404, "Document not found")
    if doc["status"] not in ("uploaded", "failed"):
        raise HTTPException(400, f"Document status is '{doc['status']}', cannot re-parse")

    docs_db.update_document_status(document_id, status="parsing")
    background_tasks.add_task(_run_parse, document_id, doc["volume_path"])

    return {"document_id": document_id, "status": "parsing"}


def _run_parse(document_id: str, volume_path: str):
    """Background task: run ai_parse_document, quality checks, and store results."""
    try:
        # Build image output path per document
        img_path = f"{IMAGE_OUTPUT_VOLUME_PATH}/{document_id}/"

        result = parse_document(volume_path, img_path)

        # Run quality heuristics
        from services.quality_checks import run_quality_checks
        flags = run_quality_checks(result["parsed_result"])

        docs_db.update_document_status(
            document_id,
            status="parsed",
            parsed_result=result["parsed_result"],
            image_output_path=result["image_output_path"],
            page_count=result["page_count"],
            element_count=result["element_count"],
            quality_flags=flags,
        )
        logger.info(f"Parse complete for {document_id} ({len(flags)} quality flags)")

    except Exception as e:
        logger.error(f"Parse failed for {document_id}: {e}", exc_info=True)
        docs_db.update_document_status(
            document_id, status="failed", error_message=str(e)
        )


@router.get("/{document_id}")
def get_document(document_id: str):
    """Get document details (without full parsed_result to keep response small)."""
    doc = docs_db.get_document(document_id)
    if not doc:
        raise HTTPException(404, "Document not found")

    stats = docs_db.get_document_feedback_stats(document_id)
    doc["feedback_stats"] = stats

    # Don't send full parsed_result in list view - it can be huge
    # Client fetches page data via /page/{page_id} endpoint
    if doc.get("parsed_result"):
        pr = doc["parsed_result"]
        doc["parsed_summary"] = {
            "page_count": doc.get("page_count", 0),
            "element_count": doc.get("element_count", 0),
            "has_parsed_result": True,
        }
        # Keep parsed_result for page-level access
    else:
        doc["parsed_summary"] = {"has_parsed_result": False}

    return doc


@router.get("/{document_id}/page/{page_id}")
def get_page_data(document_id: str, page_id: int):
    """Get page image (base64) and elements for a specific page."""
    doc = docs_db.get_document(document_id)
    if not doc:
        raise HTTPException(404, "Document not found")
    if not doc.get("parsed_result"):
        raise HTTPException(400, "Document not parsed yet")

    parsed = doc["parsed_result"]
    pages = parsed.get("document", {}).get("pages", [])

    if page_id < 0 or page_id >= len(pages):
        raise HTTPException(404, f"Page {page_id} not found (document has {len(pages)} pages)")

    page = pages[page_id]
    image_uri = page.get("image_uri")

    # Load page image
    image_data = load_page_image(image_uri) if image_uri else None

    # Get elements on this page
    elements = get_page_elements(parsed, page_id)

    # Get feedback for this page
    feedbacks = feedback_db.get_feedback_for_page(document_id, page_id)
    feedback_map = {f["element_id"]: f for f in feedbacks}

    # Get quality flags for elements on this page
    all_flags = doc.get("quality_flags") or []
    page_element_ids = {e.get("id") for e in elements}
    quality_flags_map = {}
    for flag in all_flags:
        eid = flag.get("element_id")
        if eid in page_element_ids:
            quality_flags_map.setdefault(eid, []).append(flag)

    return {
        "page_id": page_id,
        "page_number": page_id + 1,
        "total_pages": len(pages),
        "image": image_data,
        "image_uri": image_uri,
        "elements": elements,
        "feedback": feedback_map,
        "quality_flags": quality_flags_map,
    }


@router.get("/{document_id}/pdf")
def get_document_pdf(document_id: str):
    """Serve the source PDF for a document (for PDF.js rendering)."""
    from fastapi.responses import Response
    from utils.auth import get_databricks_token, get_workspace_url
    import requests as req

    doc = docs_db.get_document(document_id)
    if not doc:
        raise HTTPException(404, "Document not found")
    if not doc.get("volume_path"):
        raise HTTPException(404, "No source PDF available for this document")

    token = get_databricks_token()
    workspace_url = get_workspace_url()
    api_url = f"{workspace_url}/api/2.0/fs/files{doc['volume_path']}"

    resp = req.get(api_url, headers={"Authorization": f"Bearer {token}"}, timeout=60)
    if resp.status_code != 200:
        raise HTTPException(404, "PDF file not found in volume")

    return Response(
        content=resp.content,
        media_type="application/pdf",
        headers={"Content-Disposition": f'inline; filename="{doc["filename"]}"'},
    )


@router.delete("/{document_id}")
def delete_document(document_id: str, background_tasks: BackgroundTasks):
    """Delete a document, its feedback, and UC Volume files."""
    doc = docs_db.get_document(document_id)
    if not doc:
        raise HTTPException(404, "Document not found")

    # Delete from database FIRST (fast, user sees it gone immediately)
    volume_path = doc.get("volume_path")
    image_path = doc.get("image_output_path")
    docs_db.delete_document(document_id)

    # UC Volume cleanup in background (don't block the response)
    def _cleanup():
        from services.ingest import delete_from_volume, delete_directory_from_volume
        if volume_path:
            delete_from_volume(volume_path)
        if image_path:
            delete_directory_from_volume(image_path)

    background_tasks.add_task(_cleanup)

    return {"status": "deleted", "document_id": document_id}
