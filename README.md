# 📚 Dịch sách — Offline PDF Book Translator

Ứng dụng local chạy **hoàn toàn offline**: upload sách PDF ở ngôn ngữ bất kỳ, dịch toàn bộ sang ngôn ngữ đích bạn chọn (mặc định tiếng Việt) bằng AI local qua Ollama, đọc kết quả song ngữ trên web.

## Kiến trúc

```
Angular 21 SPA (localhost:4210) → FastAPI (localhost:8000) → Ollama (localhost:11434)
```

- **Ngôn ngữ nguồn tự động nhận diện, ngôn ngữ đích chọn sẵn**: ngôn ngữ của file PDF gốc được tự động phát hiện ngay sau khi trích xuất, không cần nhập tay. Ngôn ngữ đích chọn từ danh sách phổ biến (mặc định Tiếng Việt) hoặc tuỳ chỉnh — không giới hạn cố định, miễn model hỗ trợ.
- **Dịch hybrid 2 giai đoạn**: `translategemma` dịch thô toàn bộ sách trước → `qwen2.5:14b` biên tập lại thành văn xuôi tự nhiên bằng ngôn ngữ đích sau. Chạy theo giai đoạn (không đổi model mỗi đoạn) để máy chỉ cần giữ 1 model trong RAM tại một thời điểm. Tên riêng được trích và giữ nhất quán xuyên suốt cuốn sách trong lúc dịch (nội bộ, không có trang riêng để xem).
- **Tóm tắt theo chương**: tạo tóm tắt theo ngôn ngữ đích cho từng chương (dựa trên bản dịch), xem tại trang **Tóm tắt** — tạo theo yêu cầu sau khi dịch xong, không tự động chạy kèm job dịch.
- **Hỏi đáp về nội dung sách**: chat hỏi-đáp dựa trên bản dịch (RAG, retrieval cục bộ + `qwen2.5`), đánh index tự động sau khi dịch xong, câu trả lời stream theo từng token, hỗ trợ code block/công thức toán trong câu trả lời.
- **Đọc song ngữ**: xem bản gốc + bản dịch cạnh nhau, hoặc từng bản riêng. Giữ được in đậm/nghiêng, code block (không bị dịch, tránh hỏng cú pháp), thơ/địa chỉ (giữ xuống dòng), và hình ảnh gốc trong PDF.
- **Dịch lại từng đoạn**: mỗi đoạn văn ở trang đọc có nút ↻ (hiện khi rê chuột) để dịch lại riêng đoạn đó — hữu ích khi model dịch sai/lẫn ngôn ngữ ở một vài chỗ mà không cần dịch lại cả sách.
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

Cách nhanh nhất — 1 lệnh, tự kiểm tra/khởi động Ollama, tự pull model còn thiếu, khởi động cả backend lẫn frontend, tự mở browser:

```bash
./start.sh   # Ctrl+C để dừng tất cả
```

Hoặc chạy tay từng phần (hữu ích khi cần xem log riêng của từng service):

```bash
# Terminal 1 — backend
cd backend && source .venv/bin/activate
uvicorn app.main:app --port 8000

# Terminal 2 — frontend
cd frontend && npm start
```

Mở http://localhost:4210 → upload PDF → bấm **Dịch** → theo dõi tiến độ → **Đọc**. Sách đã dịch xong có thêm nút **Tóm tắt** (tạo tóm tắt từng chương) và **Hỏi đáp** (chat về nội dung sách).

API docs (Swagger): http://localhost:8000/docs

## Chạy bằng Docker

Đóng gói backend + frontend vào container; **Ollama vẫn chạy native trên máy host**, không đưa vào Docker — trên macOS, Docker Desktop chạy container trong 1 VM Linux không pass-through được Metal/GPU của Apple Silicon, nên Ollama trong container sẽ rơi về CPU-only và chậm đi rất nhiều.

```bash
# 1. Ollama vẫn cài + chạy native như bình thường, đã pull đủ model
ollama pull translategemma
ollama pull qwen2.5:14b-instruct-q4_K_M
ollama serve   # nếu chưa chạy sẵn

# 2. Build + chạy backend/frontend trong container
docker compose up --build   # thêm -d để chạy nền
```

Mở http://localhost:4210 như bình thường. Frontend (nginx) phục vụ Angular đã build sẵn và tự proxy `/api/*` sang backend cùng origin (giống `proxy.conf.json` lúc dev) — trình duyệt không cần biết backend chạy ở container nào. Backend nối tới Ollama trên host qua `http://host.docker.internal:11434` (khai trong `docker-compose.yml`, override được qua biến môi trường `OLLAMA_BASE_URL`).

Dữ liệu (`backend/data/`) được mount làm volume nên vẫn giữ nguyên giữa các lần `docker compose up`/`down`, giống hệt khi chạy native.

Dừng: `docker compose down` (thêm `-v` chỉ khi muốn xoá luôn dữ liệu — bình thường không cần).

## Ghi chú

- Job dịch chạy nền và lưu tiến độ sau mỗi chunk — nếu tắt máy giữa chừng, bấm dịch lại sẽ tiếp tục từ chỗ dừng (chunk đã dịch được bỏ qua).
- Tốc độ tham khảo trên M1/32GB: ~4-5 phút cho ~9 trang. Sách dài nên chạy qua đêm.
- **Máy cấu hình thấp hơn**: đổi `POLISH_MODEL` trong `backend/app/config.py` (nhớ `ollama pull` model mới trước khi đổi):

  | Cấu hình | Model | Kích thước |
  |---|---|---|
  | 8-16GB RAM | `qwen2.5:7b-instruct-q4_K_M` | ~4.7GB |
  | ≤8GB RAM / máy rất yếu | `qwen2.5:3b-instruct-q4_K_M` | ~2GB (văn phong kém tự nhiên hơn) |

  Chọn dòng Qwen2.5 vì được train đa ngôn ngữ rộng, cho tiếng Việt tự nhiên hơn các model cùng cỡ khác (Llama3.2, Gemma2). `ROUGH_MODEL` (`translategemma`, 3.3GB) đã đủ nhẹ, không cần đổi trừ khi máy dưới 8GB — lúc đó có thể bỏ hẳn bước polish, chỉ dùng rough pass để tiết kiệm tải thêm 1 model.
- Dữ liệu nằm ở `backend/data/` (gitignored): SQLite (`app.db`) + mỗi sách một thư mục (`original.pdf`, `structure.json`, `glossary.json`, `output.html`). `glossary.json` chỉ dùng nội bộ để dịch nhất quán tên riêng, có thể sửa tay file này nếu muốn ép cách dịch một tên riêng, dù không có UI riêng cho việc đó.

## Tài liệu dự án

- [AGENTS.md](AGENTS.md) — kiến trúc và quy ước cho AI agent làm việc trong repo
