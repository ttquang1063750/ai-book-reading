from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BACKEND_DIR / "data"
BOOKS_DIR = DATA_DIR / "books"
DB_PATH = DATA_DIR / "app.db"

OLLAMA_BASE_URL = "http://localhost:11434"
ROUGH_MODEL = "translategemma:latest"
POLISH_MODEL = "qwen2.5:14b-instruct-q4_K_M"

CHUNK_TOKEN_BUDGET = 1800
CHARS_PER_TOKEN_ESTIMATE = 4

CORS_ORIGINS = ["http://localhost:4200"]
