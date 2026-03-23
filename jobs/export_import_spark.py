# Databricks notebook source
"""
Spark-parallelized export/import for AI Parse Feedback.
Uses sc.parallelize() to distribute file I/O across Spark workers.
Falls back to FUSE mount for direct file reads/writes on UC Volumes.

Parameters: action, document_ids, input_path, output_path, lakebase_instance
"""

# COMMAND ----------

import os
import io
import json
import uuid
import zipfile
import html as html_lib
import logging
from datetime import datetime, timezone
from PIL import Image, ImageDraw

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("export_import_spark")

# Read parameters
action = dbutils.widgets.get("action")  # noqa: F821
document_ids_str = dbutils.widgets.get("document_ids")  # noqa: F821
input_path = dbutils.widgets.get("input_path")  # noqa: F821
output_path = dbutils.widgets.get("output_path")  # noqa: F821
lakebase_instance = dbutils.widgets.get("lakebase_instance")  # noqa: F821
catalog = dbutils.widgets.get("catalog")  # noqa: F821
schema = dbutils.widgets.get("schema")  # noqa: F821

logger.info(f"Spark job: action={action}, docs={document_ids_str}, catalog={catalog}, schema={schema}")

# COMMAND ----------

# Lakebase connection (driver-only)
import psycopg2
import psycopg2.extras


def get_lakebase_connection():
    from databricks.sdk import WorkspaceClient
    w = WorkspaceClient()
    instance = w.database.get_database_instance(lakebase_instance)
    host = instance.read_write_dns
    cred = w.database.generate_database_credential(instance_names=[lakebase_instance])
    me = w.current_user.me()
    return psycopg2.connect(
        host=host, port=5432, database=lakebase_instance,
        user=me.user_name, password=cred.token, sslmode="require"
    )


def get_db_cursor():
    conn = get_lakebase_connection()
    return conn, conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

# COMMAND ----------

# Spark-parallelized file I/O using FUSE mount

def read_file_fuse(volume_path):
    """Read a file from UC Volume via FUSE mount (works on all nodes)."""
    try:
        with open(volume_path, 'rb') as f:
            return f.read()
    except Exception as e:
        return None


def write_file_fuse(dest_path, data):
    """Write a file to UC Volume via FUSE mount (works on all nodes)."""
    os.makedirs(os.path.dirname(dest_path), exist_ok=True)
    with open(dest_path, 'wb') as f:
        f.write(data)
    return dest_path


def download_files_parallel(volume_paths, max_workers=50):
    """Download multiple files from UC Volume using ThreadPoolExecutor with FUSE."""
    from concurrent.futures import ThreadPoolExecutor
    if not volume_paths:
        return {}

    results = {}

    def _read(path):
        try:
            with open(path, 'rb') as f:
                return (path, f.read())
        except Exception:
            return (path, None)

    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        for path, data in pool.map(_read, volume_paths):
            if data is not None:
                results[path] = data

    logger.info(f"Downloaded {len(results)}/{len(volume_paths)} files via FUSE (parallel)")
    return results


def upload_files_parallel(file_items, max_workers=50):
    """Upload multiple files to UC Volume using ThreadPoolExecutor with FUSE.

    FUSE mount is MUCH faster than REST API since it uses internal cloud storage.
    """
    from concurrent.futures import ThreadPoolExecutor
    if not file_items:
        return []

    def _write(item):
        dest_path, data = item
        try:
            os.makedirs(os.path.dirname(dest_path), exist_ok=True)
            with open(dest_path, 'wb') as f:
                f.write(data)
            return dest_path
        except Exception:
            return None

    results = []
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        for r in pool.map(_write, file_items):
            if r:
                results.append(r)

    logger.info(f"Uploaded {len(results)}/{len(file_items)} files via FUSE (parallel)")
    return results

# COMMAND ----------

# Image annotation helper (driver-only, for issue images)

def render_annotated_image(raw_bytes, bbox_coord, color="#e74c3c", label=""):
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

# COMMAND ----------

def run_export():
    """Export documents — Spark-parallelized page image downloads."""
    doc_ids = [d.strip() for d in document_ids_str.split(",") if d.strip()]
    logger.info(f"Exporting {len(doc_ids)} documents (Spark mode)...")

    conn, cur = get_db_cursor()


    # Step 1: Collect all data from Lakebase (driver)
    all_docs = []
    all_page_uris = []

    for doc_id in doc_ids:
        cur.execute("SELECT * FROM documents WHERE document_id = %s", (doc_id,))
        doc = cur.fetchone()
        if not doc or not doc.get("parsed_result"):
            continue

        doc = {k: (str(v) if hasattr(v, 'hex') else v) for k, v in dict(doc).items()}

        cur.execute("SELECT * FROM feedback WHERE document_id = %s ORDER BY page_id, element_id", (doc_id,))
        feedbacks = [{k: (str(v) if hasattr(v, 'hex') else v) for k, v in dict(f).items()} for f in cur.fetchall()]

        parsed = doc.get("parsed_result", {})
        pages = parsed.get("document", {}).get("pages", [])

        for page in pages:
            uri = page.get("image_uri")
            if uri:
                all_page_uris.append(uri)

        all_docs.append({"doc": doc, "feedbacks": feedbacks})

    cur.close()
    conn.close()

    # Step 2: Download ALL page images via Spark (distributed)
    logger.info(f"Downloading {len(all_page_uris)} page images via Spark...")
    page_image_bytes = download_files_parallel(all_page_uris)

    # Step 3: Build ZIP on driver
    logger.info("Building ZIP...")
    buf = io.BytesIO()

    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for doc_data in all_docs:
            doc = doc_data["doc"]
            feedbacks = doc_data["feedbacks"]
            parsed = doc.get("parsed_result", {})
            elements = parsed.get("document", {}).get("elements", [])
            elements_by_id = {e.get("id"): e for e in elements}
            pages = parsed.get("document", {}).get("pages", [])
            feedback_map = {f["element_id"]: f for f in feedbacks}

            prefix = f"{doc['filename'].rsplit('.', 1)[0]}/" if len(all_docs) > 1 else ""

            # Source PDF (read via FUSE on driver)
            if doc.get("volume_path"):
                pdf_bytes = read_file_fuse(doc["volume_path"])
                if pdf_bytes:
                    zf.writestr(f"{prefix}source/{doc['filename']}", pdf_bytes)

            # Page images (already downloaded)
            for i, page in enumerate(pages):
                uri = page.get("image_uri")
                if uri and uri in page_image_bytes:
                    ext = uri.rsplit(".", 1)[-1] if "." in uri else "png"
                    zf.writestr(f"{prefix}pages/page_{i}.{ext}", page_image_bytes[uri])

            # Annotated issue images
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

            # Parsed result + manifest
            zf.writestr(f"{prefix}parsed_result.json", json.dumps(parsed, indent=2))

            manifest_lines = [json.dumps({
                "type": "metadata", "document_id": str(doc.get("document_id", "")),
                "filename": doc["filename"], "parse_version": "2.0",
                "page_count": len(pages), "element_count": len(elements),
                "use_case_name": doc.get("use_case_name"),
                "quality_flags": doc.get("quality_flags"),
                "exported_at": datetime.now(timezone.utc).isoformat(),
            })]
            for elem in elements:
                elem_id = elem.get("id")
                fb = feedback_map.get(elem_id)
                bbox_list = elem.get("bbox", [])
                manifest_lines.append(json.dumps({
                    "type": "element", "element_id": elem_id,
                    "page_id": bbox_list[0].get("page_id", 0) if bbox_list else 0,
                    "element_type": elem.get("type"),
                    "bbox": bbox_list[0].get("coord", []) if bbox_list else [],
                    "content": elem.get("content", ""),
                    "feedback": {"is_correct": fb.get("is_correct"), "issue_category": fb.get("issue_category"),
                                 "comment": fb.get("comment")} if fb else None,
                }))
            correct = sum(1 for f in feedbacks if f.get("is_correct"))
            issues = sum(1 for f in feedbacks if f.get("is_correct") is False)
            manifest_lines.append(json.dumps({"type": "summary", "total_elements": len(elements),
                                               "elements_reviewed": len(feedbacks), "elements_correct": correct,
                                               "elements_with_issues": issues}))
            zf.writestr(f"{prefix}manifest.jsonl", "\n".join(manifest_lines))

        if len(all_docs) > 1:
            zf.writestr("summary.json", json.dumps({"total_documents": len(all_docs)}))

    # Step 4: Write ZIP to UC Volume
    zip_bytes = buf.getvalue()
    logger.info(f"Writing {len(zip_bytes)} bytes to {output_path}")
    write_file_fuse(output_path, zip_bytes)
    logger.info("Export complete!")

# COMMAND ----------

def run_import():
    """Import documents — Spark-parallelized page image uploads."""
    logger.info(f"Importing from {input_path} (Spark mode)...")



    # Step 1: Download ZIP (driver)
    zip_bytes = read_file_fuse(input_path)
    if not zip_bytes:
        raise Exception(f"Could not read ZIP from {input_path}")

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

            parsed_path = f"{dir_prefix}parsed_result.json"
            parsed_result = None
            if parsed_path in zf.namelist():
                parsed_result = json.loads(zf.read(parsed_path).decode("utf-8"))

            # Step 2: Prepare all file uploads (extract from ZIP into memory)
            import_doc_id = str(uuid.uuid4())
            image_output_path = f"/Volumes/{catalog}/{schema}/parse_feedback_images/{import_doc_id}/"
            upload_items = []  # (dest_path, bytes)
            page_mapping = {}  # page_idx -> dest_path

            # Source PDF
            volume_path = None
            source_files = [n for n in zf.namelist() if n.startswith(dir_prefix + "source/") and not n.endswith("/") and "__MACOSX" not in n]
            if source_files:
                pdf_dest = f"/Volumes/{catalog}/{schema}/parse_feedback_source/{metadata['filename']}"
                upload_items.append((pdf_dest, zf.read(source_files[0])))
                volume_path = pdf_dest

            # Page images
            page_files = [n for n in zf.namelist() if n.startswith(dir_prefix + "pages/") and not n.endswith("/") and "__MACOSX" not in n]
            for pf in page_files:
                try:
                    fname = pf.rsplit("/", 1)[-1]
                    page_idx = int(fname.replace("page_", "").rsplit(".", 1)[0])
                    dest = f"{image_output_path}{fname}"
                    upload_items.append((dest, zf.read(pf)))
                    page_mapping[page_idx] = dest
                except Exception:
                    pass

            # Step 3: Upload ALL files via Spark (distributed!)
            logger.info(f"Uploading {len(upload_items)} files for {metadata['filename']} via Spark...")
            upload_files_parallel(upload_items)

            # Step 4: Update image_uri in parsed_result
            if parsed_result:
                pages_in_parsed = parsed_result.get("document", {}).get("pages", [])
                for page_idx, dest_path in page_mapping.items():
                    if page_idx < len(pages_in_parsed):
                        pages_in_parsed[page_idx]["image_uri"] = dest_path

            # Step 5: Insert into Lakebase (driver)
            cur.execute(
                "INSERT INTO documents (filename, volume_path, use_case_name, status, parsed_result, image_output_path, page_count, element_count, quality_flags, parsed_at) VALUES (%s, %s, %s, 'parsed', %s::jsonb, %s, %s, %s, %s::jsonb, now()) RETURNING document_id",
                (metadata["filename"], volume_path, metadata.get("use_case_name") or metadata.get("customer_name"),
                 json.dumps(parsed_result) if parsed_result else None,
                 image_output_path if page_files else None,
                 metadata.get("page_count"), metadata.get("element_count"),
                 json.dumps(metadata.get("quality_flags")) if metadata.get("quality_flags") else None)
            )
            doc_id = str(cur.fetchone()["document_id"])
            conn.commit()

            # Step 6: Bulk feedback insert
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
            logger.info(f"Imported: {metadata['filename']} ({len(upload_items)} files, {len(element_lines)} feedback)")

    cur.close()
    conn.close()
    logger.info(f"Import complete! {imported} documents imported via Spark.")

# COMMAND ----------

if action == "export":
    run_export()
elif action == "import":
    run_import()
else:
    raise ValueError(f"Unknown action: {action}")
