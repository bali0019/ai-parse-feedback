"""Feedback API endpoints: create/update, list, delete."""

import logging
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from db import feedback as feedback_db

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/feedback", tags=["feedback"])


class FeedbackCreate(BaseModel):
    document_id: str
    element_id: int
    page_id: int
    element_type: Optional[str] = None
    bbox_coords: Optional[list] = None
    is_correct: Optional[bool] = None
    issue_category: Optional[str] = None
    comment: Optional[str] = None
    suggested_content: Optional[str] = None
    suggested_type: Optional[str] = None
    reviewer: Optional[str] = None


@router.post("")
def submit_feedback(body: FeedbackCreate):
    """Submit or update feedback for a document element (upsert)."""
    feedback_id = feedback_db.upsert_feedback(
        document_id=body.document_id,
        element_id=body.element_id,
        page_id=body.page_id,
        element_type=body.element_type,
        bbox_coords=body.bbox_coords,
        is_correct=body.is_correct,
        issue_category=body.issue_category,
        comment=body.comment,
        suggested_content=body.suggested_content,
        suggested_type=body.suggested_type,
        reviewer=body.reviewer,
    )
    return {"feedback_id": feedback_id, "status": "saved"}


class BulkFeedbackItem(BaseModel):
    element_id: int
    page_id: int
    element_type: Optional[str] = None
    bbox_coords: Optional[list] = None
    is_correct: Optional[bool] = None
    issue_category: Optional[str] = None
    comment: Optional[str] = None


class BulkFeedbackCreate(BaseModel):
    document_id: str
    items: list[BulkFeedbackItem]


@router.post("/bulk")
def submit_bulk_feedback(body: BulkFeedbackCreate):
    """Submit feedback for multiple elements in a single transaction."""
    items = [
        {
            "element_id": item.element_id,
            "page_id": item.page_id,
            "element_type": item.element_type,
            "bbox_coords": item.bbox_coords,
            "is_correct": item.is_correct,
            "issue_category": item.issue_category,
            "comment": item.comment,
        }
        for item in body.items
    ]
    count = feedback_db.bulk_upsert_feedback(body.document_id, items)
    return {"status": "saved", "count": count}


@router.get("/document/{document_id}")
def get_document_feedback(document_id: str):
    """Get all feedback for a document."""
    return feedback_db.get_feedback_for_document(document_id)


@router.delete("/{feedback_id}")
def delete_feedback(feedback_id: str):
    """Delete a feedback entry."""
    feedback_db.delete_feedback(feedback_id)
    return {"status": "deleted"}
