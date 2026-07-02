# 📚 Dịch sách — Offline PDF → Vietnamese Book Translator

Ứng dụng local chạy **hoàn toàn offline**: upload sách PDF (tiếng Anh/Pháp), dịch toàn bộ sang tiếng Việt bằng AI local qua Ollama, đọc kết quả song ngữ trên web.

## Kiến trúc

```
Angular 21 SPA (localhost:4200) → FastAPI (localhost:8000) → Ollama (localhost:11434)
```

- **Dịch hybrid 2 giai đoạn**: `translategemma` dịch thô toàn bộ sách trước → `qwen2.5:14b` biên tập lại thành văn xuôi tiếng Việt tự nhiên sau. Chạy theo giai đoạn (không đổi model mỗi đoạn) để máy chỉ cần giữ 1 model trong RAM tại một thời điểm.
- **Glossary tự động**: tên riêng được trích và giữ nhất quán xuyên suốt cuốn sách — xem tại trang **Giải nghĩa** của mỗi sách.
- **Tóm tắt theo chương**: tạo tóm tắt tiếng Việt cho từng chương (dựa trên bản dịch), xem tại trang **Tóm tắt** — tạo theo yêu cầu sau khi dịch xong, không tự động chạy kèm job dịch.
- **Đọc song ngữ**: xem bản gốc + bản dịch cạnh nhau, hoặc từng bản riêng. Giữ được in đậm/nghiêng, code block (không bị dịch, tránh hỏng cú pháp), thơ/địa chỉ (giữ xuống dòng), và hình ảnh gốc trong PDF.
- Mỗi sách còn có file `output.html` độc lập tại `backend/data/books/{id}/` — mở trực tiếp bằng browser không cần chạy app.

## Yêu cầu

- macOS (Apple Silicon khuyến nghị, ≥16GB RAM)
- [Ollama](https://ollama.com) đã cài và chạy
- Python ≥3.11, Node ≥20, Angular CLI ≥21

## Cài đặt lần đầu

```bash
# 1. Models (~12GB tổng)
ollama pull translategemma
ollama pull qwen2.5:14b-instruct-q4_K_M

# 2. Backend
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -e .

# 3. Frontend
cd ../frontend
npm install
```

## Chạy

```bash
# Terminal 1 — backend
cd backend && source .venv/bin/activate
uvicorn app.main:app --port 8000

# Terminal 2 — frontend
cd frontend && npm start
```

Mở http://localhost:4200 → upload PDF → bấm **Dịch** → theo dõi tiến độ → **Đọc**. Sách đã dịch xong có thêm nút **Tóm tắt** (tạo tóm tắt từng chương) và **Giải nghĩa** (bảng tên riêng/thuật ngữ).

API docs (Swagger): http://localhost:8000/docs

## Ghi chú

- Job dịch chạy nền và lưu tiến độ sau mỗi chunk — nếu tắt máy giữa chừng, bấm dịch lại sẽ tiếp tục từ chỗ dừng (chunk đã dịch được bỏ qua).
- Tốc độ tham khảo trên M1/32GB: ~4-5 phút cho ~9 trang. Sách dài nên chạy qua đêm.
- **Máy cấu hình thấp hơn**: đổi `POLISH_MODEL` trong `backend/app/config.py` (nhớ `ollama pull` model mới trước khi đổi):

  | Cấu hình | Model | Kích thước |
  |---|---|---|
  | 8-16GB RAM | `qwen2.5:7b-instruct-q4_K_M` | ~4.7GB |
  | ≤8GB RAM / máy rất yếu | `qwen2.5:3b-instruct-q4_K_M` | ~2GB (văn phong kém tự nhiên hơn) |

  Chọn dòng Qwen2.5 vì được train đa ngôn ngữ rộng, cho tiếng Việt tự nhiên hơn các model cùng cỡ khác (Llama3.2, Gemma2). `ROUGH_MODEL` (`translategemma`, 3.3GB) đã đủ nhẹ, không cần đổi trừ khi máy dưới 8GB — lúc đó có thể bỏ hẳn bước polish, chỉ dùng rough pass để tiết kiệm tải thêm 1 model.
- Dữ liệu nằm ở `backend/data/` (gitignored): SQLite (`app.db`) + mỗi sách một thư mục (`original.pdf`, `structure.json`, `glossary.json`, `output.html`). Glossary là JSON có thể sửa tay nếu muốn ép cách dịch một tên riêng.

## Tài liệu dự án

- [AGENTS.md](AGENTS.md) — kiến trúc và quy ước cho AI agent làm việc trong repo
