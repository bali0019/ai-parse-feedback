"""AI Parse Feedback - FastAPI application entry point."""

import logging
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(
    title="AI Parse Feedback API",
    description="Human-in-the-loop review of ai_parse_document results with bounding box feedback",
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Run database migrations on startup
@app.on_event("startup")
def startup():
    try:
        from db.migrations import run_migrations
        run_migrations()
    except Exception as e:
        logger.warning(f"Database migration skipped (Lakebase may not be configured): {e}")


# Include API routers
from api.documents import router as documents_router
from api.feedback import router as feedback_router
from api.export import router as export_router

app.include_router(documents_router)
app.include_router(feedback_router)
app.include_router(export_router)

# Health check
@app.get("/health", tags=["system"])
def health():
    return {"status": "ok", "app": "ai-parse-feedback"}


# Serve React frontend (built files)
FRONTEND_DIST = Path(__file__).resolve().parent.parent / "frontend" / "dist"
if FRONTEND_DIST.exists():
    logger.info(f"Serving React frontend from {FRONTEND_DIST}")
    app.mount("/assets", StaticFiles(directory=str(FRONTEND_DIST / "assets")), name="assets")

    @app.get("/", tags=["frontend"])
    async def serve_frontend():
        index = FRONTEND_DIST / "index.html"
        if index.exists():
            return FileResponse(str(index))
        return {"message": "Frontend not built. Run 'npm run build' in frontend directory."}

    @app.get("/{full_path:path}", tags=["frontend"], include_in_schema=False)
    async def catch_all(full_path: str):
        if full_path.startswith(("api/", "docs", "redoc", "health", "openapi")):
            return {"error": "Not found"}

        file_path = FRONTEND_DIST / full_path
        if file_path.exists() and file_path.is_file():
            return FileResponse(str(file_path))

        index = FRONTEND_DIST / "index.html"
        if index.exists():
            return FileResponse(str(index))
        return {"message": "Frontend not built"}
else:
    logger.warning(f"Frontend dist not found at {FRONTEND_DIST}")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
