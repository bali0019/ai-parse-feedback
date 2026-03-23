# Databricks notebook source
"""
Background job for export/import of AI Parse Feedback documents.
Triggered by the app via w.jobs.run_now() with parameters.

Parameters:
  - action: "export" or "import"
  - document_ids: comma-separated document IDs (for export)
  - input_path: UC Volume path to ZIP file (for import)
  - output_path: UC Volume path to write ZIP file (for export)
  - lakebase_instance: Lakebase instance name for DB credentials
"""

# COMMAND ----------

import os
import io
import json
import uuid
import zipfile
import html as html_lib
import logging
import requests
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from PIL import Image, ImageDraw

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("export_import_handler")

# Read parameters
action = dbutils.widgets.get("action")  # noqa: F821
document_ids_str = dbutils.widgets.get("document_ids")  # noqa: F821
input_path = dbutils.widgets.get("input_path")  # noqa: F821
output_path = dbutils.widgets.get("output_path")  # noqa: F821
lakebase_instance = dbutils.widgets.get("lakebase_instance")  # noqa: F821
catalog = dbutils.widgets.get("catalog")  # noqa: F821
schema = dbutils.widgets.get("schema")  # noqa: F821

logger.info(f"Action: {action}, docs: {document_ids_str}, catalog: {catalog}, schema: {schema}")

# COMMAND ----------

# Lakebase connection setup
import psycopg2
import psycopg2.extras


def get_lakebase_connection():
    """Connect to Lakebase using OAuth."""
    from databricks.sdk import WorkspaceClient
    w = WorkspaceClient()

    # Get connection details
    instance = w.database.get_database_instance(lakebase_instance)
    host = instance.read_write_dns

    # Generate credential
    cred = w.database.generate_database_credential(instance_names=[lakebase_instance])
    token = cred.token

    # Get user
    me = w.current_user.me()
    user = me.user_name

    return psycopg2.connect(
        host=host, port=5432, database=lakebase_instance,
        user=user, password=token, sslmode="require"
    )


def get_db_cursor():
    """Get a RealDictCursor."""
    conn = get_lakebase_connection()
    return conn, conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

# COMMAND ----------

# File download/upload helpers
from databricks.sdk import WorkspaceClient

w = WorkspaceClient()


def download_file(volume_path):
    """Download a file from UC Volume."""
    try:
        resp = w.files.download(volume_path)
        return resp.contents.read()
    except Exception as e:
        logger.warning(f"Could not download {volume_path}: {e}")
        return None


def download_files_parallel(paths, max_workers=50):
    """Download multiple files in parallel."""
    results = {}
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = {pool.submit(download_file, p): p for p in paths}
        for future in futures:
            path = futures[future]
            try:
                data = future.result()
                if data:
                    results[path] = data
            except Exception:
                pass
    return results


def upload_file(volume_path, data):
    """Upload a file to UC Volume."""
    w.files.upload(volume_path, io.BytesIO(data), overwrite=True)

# COMMAND ----------

# Export logic

def render_annotated_image(raw_bytes, bbox_coord, color="#e74c3c", label=""):
    """Draw a bounding box overlay on an image."""
    img = Image.open(io.BytesIO(raw_bytes)).convert("RGBA")
    overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    x1, y1, x2, y2 = bbox_coord
    r, g, b = int(color[1:3], 16), int(color[3:5], 16), int(color[5:7], 16)
    draw.rectangle([x1, y1, x2, y2], fill=(r, g, b, 40), outline=(r, g, b, 255), width=3)
    if label:
        draw.rectangle([x1, max(0, y1 - 18), x1 + len(label) * 7, y1], fill=(r, g, b, 220))
        draw.text((x1 + 4, max(0, y1 - 17)), label, fill=(255, 255, 255, 255))
    img = Image.alpha_composite(img, overlay).convert("RGB")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def build_doc_zip_content(zf, doc, feedbacks, prefix=""):
    """Add one document's content to a ZIP file."""
    parsed = doc.get("parsed_result", {})
    elements = parsed.get("document", {}).get("elements", [])
    elements_by_id = {e.get("id"): e for e in elements}
    pages = parsed.get("document", {}).get("pages", [])
    feedback_map = {f["element_id"]: f for f in feedbacks}

    # 1. Source PDF
    if doc.get("volume_path"):
        pdf_bytes = download_file(doc["volume_path"])
        if pdf_bytes:
            zf.writestr(f"{prefix}source/{doc['filename']}", pdf_bytes)

    # 2. ALL page images (parallel)
    page_uris = [p.get("image_uri") for p in pages if p.get("image_uri")]
    page_image_bytes = download_files_parallel(page_uris, max_workers=50)

    for i, page in enumerate(pages):
        uri = page.get("image_uri")
        if uri and uri in page_image_bytes:
            ext = uri.rsplit(".", 1)[-1] if "." in uri else "png"
            zf.writestr(f"{prefix}pages/page_{i}.{ext}", page_image_bytes[uri])

    # 3. Annotated issue images
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
                            label=f"{elem.get('type', '')} #{f['element_id']}"
                        )
                        zf.writestr(f"{prefix}issues/page_{pid + 1}_element_{f['element_id']}.png", annotated)
                        break

    # 4. Parsed result
    zf.writestr(f"{prefix}parsed_result.json", json.dumps(parsed, indent=2))

    # 5. Manifest
    manifest_lines = [json.dumps({
        "type": "metadata", "document_id": str(doc.get("document_id", "")),
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
    issue_breakdown = {}
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

    # 6. Issues report HTML
    if issue_feedbacks:
        cards = []
        for f in issue_feedbacks:
            elem = elements_by_id.get(f["element_id"], {})
            pid = f.get("page_id", 0)
            cat = f.get("issue_category", "other")
            comment = html_lib.escape(f.get("comment") or "No comment")
            elem_type = html_lib.escape(f.get("element_type") or elem.get("type", ""))
            img_file = f"issues/page_{pid + 1}_element_{f['element_id']}.png"
            cards.append(f'<div style="border:1px solid #e0e0e0;border-radius:8px;margin:16px 0;overflow:hidden"><div style="background:#f8f9fa;padding:10px 16px;border-bottom:1px solid #e0e0e0"><span style="background:#e74c3c20;color:#e74c3c;padding:3px 10px;border-radius:12px;font-size:12px;font-weight:600">{html_lib.escape(cat.replace("_"," "))}</span> <span style="font-size:12px;color:#666">Element #{f["element_id"]} · {elem_type} · Page {pid+1}</span></div><div style="padding:16px"><img src="{img_file}" style="max-width:100%;border:1px solid #ddd;border-radius:4px" /><p style="margin:12px 0 4px;font-size:14px"><strong>Feedback:</strong> {comment}</p></div></div>')
        report = f'<!DOCTYPE html><html><head><meta charset="UTF-8"><title>Issues Report - {html_lib.escape(doc["filename"])}</title></head><body style="font-family:sans-serif;max-width:900px;margin:0 auto;padding:30px"><h1>Issues Report: {html_lib.escape(doc["filename"])}</h1><p>{len(issue_feedbacks)} issues found</p>{"".join(cards)}</body></html>'
        zf.writestr(f"{prefix}issues_report.html", report)

    return {"correct": correct, "issues": issues}

# COMMAND ----------

def run_export():
    """Export documents to a ZIP file in UC Volume."""
    doc_ids = [d.strip() for d in document_ids_str.split(",") if d.strip()]
    logger.info(f"Exporting {len(doc_ids)} documents...")

    conn, cur = get_db_cursor()
    buf = io.BytesIO()

    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for i, doc_id in enumerate(doc_ids):
            logger.info(f"Processing doc {i+1}/{len(doc_ids)}: {doc_id}")

            cur.execute("SELECT * FROM documents WHERE document_id = %s", (doc_id,))
            doc = cur.fetchone()
            if not doc or not doc.get("parsed_result"):
                continue

            doc = {k: (str(v) if hasattr(v, 'hex') else v) for k, v in dict(doc).items()}

            cur.execute("SELECT * FROM feedback WHERE document_id = %s ORDER BY page_id, element_id", (doc_id,))
            feedbacks = [{k: (str(v) if hasattr(v, 'hex') else v) for k, v in dict(f).items()} for f in cur.fetchall()]

            prefix = f"{doc['filename'].rsplit('.', 1)[0]}/" if len(doc_ids) > 1 else ""
            build_doc_zip_content(zf, doc, feedbacks, prefix=prefix)

        if len(doc_ids) > 1:
            zf.writestr("summary.json", json.dumps({"total_documents": len(doc_ids)}))

    cur.close()
    conn.close()

    # Write ZIP to UC Volume
    zip_bytes = buf.getvalue()
    logger.info(f"Writing {len(zip_bytes)} bytes to {output_path}")
    w.files.upload(output_path, io.BytesIO(zip_bytes), overwrite=True)
    logger.info("Export complete!")


def run_import():
    """Import documents from a ZIP file in UC Volume."""
    logger.info(f"Importing from {input_path}...")

    # Download ZIP
    zip_bytes = download_file(input_path)
    if not zip_bytes:
        raise Exception(f"Could not download ZIP from {input_path}")

    conn, cur = get_db_cursor()
    buf = io.BytesIO(zip_bytes)
    imported = 0

    with zipfile.ZipFile(buf, "r") as zf:
        manifests = [n for n in zf.namelist() if n.endswith("manifest.jsonl") and "__MACOSX" not in n]
        logger.info(f"Found {len(manifests)} manifest(s)")

        for manifest_path in manifests:
            dir_prefix = manifest_path.rsplit("manifest.jsonl", 1)[0]
            manifest_text = zf.read(manifest_path).decode("utf-8")
            lines = [json.loads(line) for line in manifest_text.strip().split("\n") if line.strip()]

            metadata = next((l for l in lines if l.get("type") == "metadata"), None)
            if not metadata:
                continue

            # Read parsed_result
            parsed_path = f"{dir_prefix}parsed_result.json"
            parsed_result = None
            if parsed_path in zf.namelist():
                parsed_result = json.loads(zf.read(parsed_path).decode("utf-8"))

            # Prepare all uploads (extract from ZIP into memory first — fast)
            volume_path = None
            import_doc_id = str(uuid.uuid4())
            image_output_path = f"/Volumes/{catalog}/{schema}/parse_feedback_images/{import_doc_id}/"
            uploads = []  # (dest_path, data, page_idx_or_none)

            # Source PDF
            source_files = [n for n in zf.namelist() if n.startswith(dir_prefix + "source/") and not n.endswith("/") and "__MACOSX" not in n]
            if source_files:
                pdf_dest = f"/Volumes/{catalog}/{schema}/parse_feedback_source/{metadata['filename']}"
                uploads.append((pdf_dest, zf.read(source_files[0]), None))
                volume_path = pdf_dest

            # Page images
            page_files = [n for n in zf.namelist() if n.startswith(dir_prefix + "pages/") and not n.endswith("/") and "__MACOSX" not in n]
            pages_in_parsed = parsed_result.get("document", {}).get("pages", []) if parsed_result else []

            for pf in page_files:
                try:
                    fname = pf.rsplit("/", 1)[-1]
                    page_idx = int(fname.replace("page_", "").rsplit(".", 1)[0])
                    dest = f"{image_output_path}{fname}"
                    uploads.append((dest, zf.read(pf), page_idx))
                except Exception as e:
                    logger.warning(f"Could not prepare page image {pf}: {e}")

            # Upload ALL files in parallel (source PDF + page images together)
            logger.info(f"Uploading {len(uploads)} files in parallel...")

            def _upload_one(item):
                dest_path, data, page_idx = item
                try:
                    upload_file(dest_path, data)
                    return dest_path, page_idx
                except Exception as e:
                    logger.warning(f"Upload failed for {dest_path}: {e}")
                    return None, page_idx

            with ThreadPoolExecutor(max_workers=50) as pool:
                for dest_path, page_idx in pool.map(_upload_one, uploads):
                    if dest_path and page_idx is not None and page_idx < len(pages_in_parsed):
                        pages_in_parsed[page_idx]["image_uri"] = dest_path

            logger.info(f"All {len(uploads)} files uploaded")

            # Insert document
            cur.execute(
                "INSERT INTO documents (filename, volume_path, use_case_name, status, parsed_result, image_output_path, page_count, element_count, quality_flags, parsed_at) VALUES (%s, %s, %s, 'parsed', %s::jsonb, %s, %s, %s, %s::jsonb, now()) RETURNING document_id",
                (metadata["filename"], volume_path, metadata.get("use_case_name") or metadata.get("customer_name"), json.dumps(parsed_result) if parsed_result else None,
                 image_output_path if page_files else None, metadata.get("page_count"), metadata.get("element_count"),
                 json.dumps(metadata.get("quality_flags")) if metadata.get("quality_flags") else None)
            )
            doc_id = str(cur.fetchone()["document_id"])
            conn.commit()

            # Import feedback (bulk)
            element_lines = [l for l in lines if l.get("type") == "element" and l.get("feedback")]
            if element_lines:
                params = []
                for elem in element_lines:
                    fb = elem["feedback"]
                    if fb:
                        params.append((doc_id, elem["element_id"], elem["page_id"], elem.get("element_type"),
                                       json.dumps(elem.get("bbox")) if elem.get("bbox") else None,
                                       fb.get("is_correct"), fb.get("issue_category"), fb.get("comment")))
                if params:
                    cur.executemany(
                        "INSERT INTO feedback (document_id, element_id, page_id, element_type, bbox_coords, is_correct, issue_category, comment) VALUES (%s, %s, %s, %s, %s::jsonb, %s, %s, %s) ON CONFLICT (document_id, element_id) DO UPDATE SET is_correct=EXCLUDED.is_correct, issue_category=EXCLUDED.issue_category, comment=EXCLUDED.comment, updated_at=now()",
                        params
                    )
                    conn.commit()

            imported += 1
            logger.info(f"Imported doc: {metadata['filename']} ({len(element_lines)} feedback items)")

    cur.close()
    conn.close()
    logger.info(f"Import complete! {imported} documents imported.")

# COMMAND ----------

if action == "export":
    run_export()
elif action == "import":
    run_import()
else:
    raise ValueError(f"Unknown action: {action}")
