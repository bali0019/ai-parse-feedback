"""Fetch page images from UC Volume and return as base64."""

import base64
import logging
from io import BytesIO

import requests
from PIL import Image, ImageDraw

from utils.auth import get_databricks_token, get_workspace_url

logger = logging.getLogger(__name__)


def load_page_image(image_uri: str, token: str = None) -> dict | None:
    """
    Load a page image from UC Volume via Files API.

    Args:
        image_uri: UC Volume path
        token: Pre-fetched OAuth token (avoids re-generating per call)

    Returns:
        Dict with base64 data URI, width, height, or None on failure.
    """
    if not image_uri:
        return None

    if not token:
        token = get_databricks_token()
    workspace_url = get_workspace_url()
    api_url = f"{workspace_url}/api/2.0/fs/files{image_uri}"

    try:
        response = requests.get(
            api_url,
            headers={"Authorization": f"Bearer {token}"},
            timeout=30,
        )
        response.raise_for_status()

        img_bytes = response.content
        img = Image.open(BytesIO(img_bytes))
        width, height = img.size

        ext = image_uri.rsplit(".", 1)[-1].lower() if "." in image_uri else "png"
        mime = "image/jpeg" if ext in ("jpg", "jpeg") else "image/png"

        b64 = base64.b64encode(img_bytes).decode("utf-8")
        data_uri = f"data:{mime};base64,{b64}"

        return {
            "data_uri": data_uri,
            "width": width,
            "height": height,
            "size_bytes": len(img_bytes),
        }

    except Exception as e:
        logger.error(f"Failed to load image {image_uri}: {e}")
        return None


def render_annotated_image(raw_bytes: bytes, bbox_coord: list, color: str = "#e74c3c", label: str = "") -> bytes:
    """
    Draw a bounding box overlay on an image and return as PNG bytes.

    Args:
        raw_bytes: Original image bytes
        bbox_coord: [x1, y1, x2, y2]
        color: Hex color for the bbox
        label: Label text to draw above the bbox
    """
    img = Image.open(BytesIO(raw_bytes)).convert("RGBA")

    # Draw semi-transparent overlay
    overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)

    x1, y1, x2, y2 = bbox_coord
    # Parse hex color
    r = int(color[1:3], 16)
    g = int(color[3:5], 16)
    b = int(color[5:7], 16)

    # Fill with transparency
    draw.rectangle([x1, y1, x2, y2], fill=(r, g, b, 40), outline=(r, g, b, 255), width=3)

    # Label
    if label:
        draw.rectangle([x1, max(0, y1 - 18), x1 + len(label) * 7, y1], fill=(r, g, b, 220))
        draw.text((x1 + 4, max(0, y1 - 17)), label, fill=(255, 255, 255, 255))

    img = Image.alpha_composite(img, overlay)
    img = img.convert("RGB")

    buf = BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def get_page_elements(parsed_result: dict, page_id: int) -> list[dict]:
    """Extract elements for a specific page from parsed result."""
    document = parsed_result.get("document", {})
    elements = document.get("elements", [])

    page_elements = []
    for elem in elements:
        for bbox in elem.get("bbox", []):
            if bbox.get("page_id") == page_id:
                page_elements.append(elem)
                break

    return page_elements
