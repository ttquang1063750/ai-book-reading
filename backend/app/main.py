from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.books import router as books_router
from app.api.glossary import router as glossary_router
from app.api.html import router as html_router
from app.api.jobs import router as jobs_router
from app.api.summaries import router as summaries_router
from app.config import CORS_ORIGINS
from app.db import init_db

app = FastAPI(title="Book Translator")

app.include_router(books_router)
app.include_router(glossary_router)
app.include_router(html_router)
app.include_router(jobs_router)
app.include_router(summaries_router)

app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def on_startup() -> None:
    init_db()


@app.get("/api/health")
def health() -> dict:
    return {"status": "ok"}
