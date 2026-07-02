# AGENTS.md

## Project
Local, fully offline app that uploads English/French PDF books and translates them entirely into Vietnamese using local LLMs via Ollama. No cloud calls anywhere. Personal single-user tool — no auth, no multi-tenancy.

The first working version is complete and verified end-to-end; the sections below record the architecture and conventions to follow when extending it.

## Stack
- **Backend**: Python 3.11 + FastAPI, in `backend/`. Async throughout (calls to Ollama are HTTP).
- **Frontend**: Angular 21, standalone components + signals (no NgModules, no NgRx), in `frontend/`.
- **Local LLMs via Ollama** (`localhost:11434`, must already be running):
  - `translategemma:latest` — rough/fast translation pass.
  - `qwen2.5:14b-instruct-q4_K_M` — literary polish pass (fallback: `qwen2.5:7b-instruct-q4_K_M` if too slow on this machine).
- **PDF parsing**: PyMuPDF (`fitz`), using `page.get_text("dict")` for font-size metadata to distinguish headings from paragraphs.
- **Persistence**: SQLite (stdlib `sqlite3`, no ORM) for book/job status rows; per-book JSON files (`structure.json`, `glossary.json`) for content. No Postgres, no SQLAlchemy.
- **Job execution**: in-process `asyncio.create_task`, sequential (not concurrent) chunk processing — no Celery/Redis. Translation runs as **two whole-book passes** (`rough_translating` then `polishing`), not interleaved per chunk — each pass loads only its own model for the whole book, so low-RAM machines that can't keep both models warm don't pay a reload cost every chunk. Glossary is fully built by the end of the rough pass, before polishing starts (block model has separate `rough_text` and `translated_text` fields — see `book_structure.py`).
- **Output**: backend renders HTML from `structure.json` via Jinja2; served as a fragment to Angular (`[innerHTML]` after `DomSanitizer`) and also saved as a standalone `output.html` file per book.
- **Glossary page** (`/books/:id/glossary`): reads `glossary.json` (already built during the rough pass) and renders it as a term table — no separate pipeline.
- **Chapter summaries** (`/books/:id/summary`): a second job type (`jobs.job_type = 'summarize'`, reuses the same `jobs` table/polling infra as translation). `pipeline/summarize.py` splits blocks into chapters by level-1 heading, summarizes each chapter's *translated* text via the polish model, map-reducing chapters that exceed `SUMMARY_GROUP_TOKEN_BUDGET`. Stored in `data/books/{id}/summaries.json` keyed by heading block id.

## Explicit non-goals (don't add these)
- No `torch`/`transformers`/`ctranslate2`/NLLB — translation only goes through Ollama's REST API.
- No auth, no multi-user support, no cloud deployment.
- No NgRx — plain injectable signal stores only.
- No `resource()`/`httpResource()`/`rxResource()` in Angular yet — verified still `@experimental` in the installed 21.2.17 typings (`node_modules/@angular/*/types/*.d.ts`); revisit when promoted stable. Polling uses the modern stable interop pattern instead: RxJS `timer` + `exhaustMap` + `takeWhile` converted via `toSignal`.
- No iframe for the reader view.

## Directory layout
```
backend/
  app/
    main.py, config.py, db.py
    api/         # books.py, jobs.py, html.py — FastAPI routers
    ingestion/   # pdf_extract.py, structure.py
    pipeline/    # chunking.py, translate.py, ollama_client.py, job_runner.py
    rendering/   # html_render.py, templates/book.html.jinja2
    models/      # schemas.py (Pydantic API models), book_structure.py (Block model)
  data/          # gitignored, created at runtime — books/{id}/{original.pdf,structure.json,glossary.json,output.html}, app.db
frontend/
  src/app/
    core/        # books.store.ts (signals), books-api.service.ts, models/
    features/    # library/, job-progress/, reader/
```

## Running locally
- Backend: `cd backend && source .venv/bin/activate && uvicorn app.main:app --reload --port 8000`
- Frontend: `cd frontend && ng serve` (dev server on `localhost:4200`)
- Ollama must be running (`ollama serve`) with both models pulled (`ollama list` to check).

## Working conventions
- Work in small, verifiable steps — implement one module/endpoint at a time, verify it (manually via `/docs`, a script, or the Preview tool), then check in with the user before moving to the next step.
- Prefer stdlib and the minimal dependency set already listed in the plan over adding new libraries.
- Keep prompts to local LLMs and any translated content out of chat responses beyond short illustrative snippets — don't reproduce large verbatim excerpts of source books in conversation.
