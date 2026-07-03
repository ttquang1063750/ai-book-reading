import os
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BACKEND_DIR / "data"
BOOKS_DIR = DATA_DIR / "books"
DB_PATH = DATA_DIR / "app.db"

# Overridable via env for Docker, where Ollama runs on the host, not in a container
# (containerizing Ollama on macOS would lose Metal/GPU acceleration — see AGENTS.md).
OLLAMA_BASE_URL = os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434")
ROUGH_MODEL = "translategemma:latest"
POLISH_MODEL = "qwen2.5:14b-instruct-q4_K_M"

CHUNK_TOKEN_BUDGET = 1800
CHARS_PER_TOKEN_ESTIMATE = 4

MAX_UPLOAD_BYTES = 200 * 1024 * 1024  # 200MB — generous for a scanned book, still bounded

CORS_ORIGINS = os.environ.get("CORS_ORIGINS", "http://localhost:4210").split(",")
