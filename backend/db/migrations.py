"""Auto-create tables on startup."""

import logging
from db.connection import get_connection

logger = logging.getLogger(__name__)

MIGRATIONS = [
    # Documents table
    """
    CREATE TABLE IF NOT EXISTS documents (
        document_id     UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        filename        TEXT NOT NULL,
        volume_path     TEXT,
        image_output_path TEXT,
        parsed_result   JSONB,
        page_count      INTEGER,
        element_count   INTEGER,
        status          TEXT DEFAULT 'uploaded',
        error_message   TEXT,
        uploaded_by     TEXT,
        uploaded_at     TIMESTAMPTZ DEFAULT now(),
        parsed_at       TIMESTAMPTZ,
        updated_at      TIMESTAMPTZ DEFAULT now()
    )
    """,
    # Feedback table
    """
    CREATE TABLE IF NOT EXISTS feedback (
        feedback_id     UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        document_id     UUID NOT NULL REFERENCES documents(document_id) ON DELETE CASCADE,
        element_id      INTEGER NOT NULL,
        page_id         INTEGER NOT NULL,
        element_type    TEXT,
        bbox_coords     JSONB,
        is_correct      BOOLEAN,
        issue_category  TEXT,
        comment         TEXT,
        suggested_content TEXT,
        suggested_type  TEXT,
        reviewer        TEXT,
        created_at      TIMESTAMPTZ DEFAULT now(),
        updated_at      TIMESTAMPTZ DEFAULT now()
    )
    """,
    # Indexes
    "CREATE INDEX IF NOT EXISTS idx_feedback_document ON feedback(document_id)",
    """
    CREATE UNIQUE INDEX IF NOT EXISTS idx_feedback_element
    ON feedback(document_id, element_id)
    """,
    # Rename customer_name → use_case_name (existing installs), or add use_case_name (fresh installs)
    """DO $$ BEGIN
        IF EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='documents' AND column_name='customer_name') THEN
            IF EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='documents' AND column_name='use_case_name') THEN
                UPDATE documents SET use_case_name = customer_name WHERE use_case_name IS NULL AND customer_name IS NOT NULL;
                ALTER TABLE documents DROP COLUMN customer_name;
            ELSE
                ALTER TABLE documents RENAME COLUMN customer_name TO use_case_name;
            END IF;
        ELSE
            ALTER TABLE documents ADD COLUMN IF NOT EXISTS use_case_name TEXT;
        END IF;
    END $$""",
    "ALTER TABLE documents ADD COLUMN IF NOT EXISTS quality_flags JSONB",
]


def run_migrations():
    """Run all migrations."""
    logger.info("Running database migrations...")
    with get_connection() as conn:
        cursor = conn.cursor()
        for sql in MIGRATIONS:
            try:
                cursor.execute(sql)
            except Exception as e:
                logger.warning(f"Migration statement warning: {e}")
        cursor.close()
    logger.info("Database migrations complete.")
