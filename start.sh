#!/usr/bin/env bash
# Start toàn bộ ứng dụng Dịch sách: Ollama + FastAPI backend + Angular frontend.
# Dùng: ./start.sh   (Ctrl+C để dừng tất cả)

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKEND_PORT=8000
FRONTEND_PORT=4210
OLLAMA_URL="http://localhost:11434"

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[0;33m'; NC='\033[0m'
info()  { echo -e "${GREEN}[start]${NC} $1"; }
warn()  { echo -e "${YELLOW}[start]${NC} $1"; }
fail()  { echo -e "${RED}[start]${NC} $1"; exit 1; }

PIDS=()
cleanup() {
  echo ""
  info "Đang dừng các tiến trình..."
  for pid in "${PIDS[@]:-}"; do
    kill "$pid" 2>/dev/null || true
  done
  wait 2>/dev/null || true
  info "Đã dừng. Tạm biệt!"
}
trap cleanup EXIT INT TERM

# ---------- 1. Ollama ----------
if curl -s --max-time 2 "$OLLAMA_URL/api/tags" > /dev/null 2>&1; then
  info "Ollama đang chạy."
else
  command -v ollama > /dev/null || fail "Chưa cài Ollama — cài từ https://ollama.com"
  warn "Ollama chưa chạy — đang khởi động..."
  ollama serve > /tmp/ollama-serve.log 2>&1 &
  PIDS+=($!)
  for _ in $(seq 1 20); do
    curl -s --max-time 2 "$OLLAMA_URL/api/tags" > /dev/null 2>&1 && break
    sleep 0.5
  done
  curl -s --max-time 2 "$OLLAMA_URL/api/tags" > /dev/null 2>&1 || fail "Không khởi động được Ollama (xem /tmp/ollama-serve.log)"
  info "Ollama đã sẵn sàng."
fi

# ---------- 2. Kiểm tra models ----------
MODELS=$(curl -s "$OLLAMA_URL/api/tags")
for model in "translategemma" "qwen2.5:14b-instruct-q4_K_M"; do
  if echo "$MODELS" | grep -q "$model"; then
    info "Model $model: OK"
  else
    warn "Thiếu model $model — đang tải (có thể mất vài phút)..."
    ollama pull "$model" || fail "Không tải được $model"
  fi
done

# ---------- 3. Backend ----------
[ -d "$ROOT/backend/.venv" ] || fail "Chưa có backend/.venv — chạy: cd backend && python3 -m venv .venv && source .venv/bin/activate && pip install -e ."

if lsof -ti tcp:$BACKEND_PORT > /dev/null 2>&1; then
  warn "Cổng $BACKEND_PORT đang bận — bỏ qua khởi động backend (đã chạy sẵn?)."
else
  info "Khởi động backend (cổng $BACKEND_PORT)..."
  (cd "$ROOT/backend" && .venv/bin/uvicorn app.main:app --port $BACKEND_PORT) > /tmp/book-backend.log 2>&1 &
  PIDS+=($!)
  for _ in $(seq 1 20); do
    curl -s --max-time 2 "http://localhost:$BACKEND_PORT/api/health" > /dev/null 2>&1 && break
    sleep 0.5
  done
  curl -s "http://localhost:$BACKEND_PORT/api/health" > /dev/null 2>&1 || fail "Backend không phản hồi (xem /tmp/book-backend.log)"
  info "Backend sẵn sàng: http://localhost:$BACKEND_PORT (API docs: /docs)"
fi

# ---------- 4. Frontend ----------
[ -d "$ROOT/frontend/node_modules" ] || fail "Chưa có frontend/node_modules — chạy: cd frontend && npm install"

if lsof -ti tcp:$FRONTEND_PORT > /dev/null 2>&1; then
  warn "Cổng $FRONTEND_PORT đang bận — bỏ qua khởi động frontend (đã chạy sẵn?)."
else
  info "Khởi động frontend (cổng $FRONTEND_PORT)..."
  (cd "$ROOT/frontend" && npm start) > /tmp/book-frontend.log 2>&1 &
  PIDS+=($!)
  for _ in $(seq 1 60); do
    curl -s --max-time 2 "http://localhost:$FRONTEND_PORT" > /dev/null 2>&1 && break
    sleep 1
  done
  curl -s "http://localhost:$FRONTEND_PORT" > /dev/null 2>&1 || fail "Frontend không phản hồi (xem /tmp/book-frontend.log)"
fi

echo ""
info "✅ Tất cả đã sẵn sàng!  Mở: http://localhost:$FRONTEND_PORT"
info "   (log: /tmp/book-backend.log, /tmp/book-frontend.log — Ctrl+C để dừng)"

# mở browser (chỉ macOS)
command -v open > /dev/null && open "http://localhost:$FRONTEND_PORT"

wait
