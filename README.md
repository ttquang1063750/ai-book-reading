# 📚 Dịch sách — Offline Book Translator

![tests](https://img.shields.io/badge/tests-83_passing-brightgreen)
![backend](https://img.shields.io/badge/backend-Python_3.11-blue)
![frontend](https://img.shields.io/badge/frontend-Angular_21-DD0031)
![LLM](https://img.shields.io/badge/LLM-Ollama_local-8A2BE2)
![privacy](https://img.shields.io/badge/privacy-100%25_offline-success)
![platform](https://img.shields.io/badge/platform-macOS-lightgrey)

Đọc sách nước ngoài bằng ngôn ngữ bạn muốn, không cần gửi nội dung sách lên bất kỳ dịch vụ cloud nào. Upload một cuốn sách, ứng dụng tự trích xuất nội dung, dịch toàn bộ bằng AI chạy local qua [Ollama](https://ollama.com), rồi cho đọc song ngữ ngay trên trình duyệt — kèm tóm tắt theo chương và hỏi đáp về nội dung sách.

## Tính năng

- **Hỗ trợ nhiều định dạng** — PDF, EPUB, và về cơ bản bất kỳ định dạng nào PyMuPDF đọc được (không giới hạn danh sách cứng).
- **Tự nhận diện ngôn ngữ nguồn**, chọn ngôn ngữ đích từ danh sách phổ biến hoặc tuỳ ý (mặc định Tiếng Việt).
- **Dịch chất lượng cao** qua 2 giai đoạn: dịch thô rồi biên tập lại thành văn xuôi tự nhiên, giữ tên riêng nhất quán xuyên suốt cuốn sách.
- **Đọc song ngữ** — bản gốc và bản dịch cạnh nhau hoặc riêng từng bản, giữ định dạng in đậm/nghiêng, code block, thơ, và hình ảnh gốc.
- **Dịch lại từng đoạn** khi một chỗ nào đó dịch chưa ổn, không cần dịch lại cả cuốn.
- **Tóm tắt theo chương** và **hỏi đáp (chat) về nội dung sách** dựa trên bản dịch, trả lời stream theo từng token.
- Mỗi sách còn xuất ra một file `output.html` độc lập, mở thẳng bằng browser không cần chạy app.

## Kiến trúc

```
Angular 21 SPA (localhost:4210) → FastAPI (localhost:8000) → Ollama (localhost:11434)
```

Toàn bộ pipeline chạy local: PyMuPDF trích xuất cấu trúc sách (heading/đoạn văn/thơ/code/ảnh dựa trên cỡ chữ) → hai model Ollama dịch theo 2 giai đoạn (dịch thô, rồi biên tập) → kết quả render thành HTML để đọc, đồng thời index lại để phục vụ chat hỏi-đáp (RAG, cosine similarity thuần numpy, không cần vector DB). Chi tiết kỹ thuật và các quyết định thiết kế nằm ở [AGENTS.md](AGENTS.md).

## Yêu cầu

- macOS (Apple Silicon khuyến nghị, ≥16GB RAM)
- [Ollama](https://ollama.com) đã cài
- Python ≥3.11, Node ≥20, Angular CLI ≥21

## Bắt đầu nhanh

```bash
# Cài đặt lần đầu
ollama pull translategemma
ollama pull qwen2.5:14b-instruct-q4_K_M
ollama pull bge-m3   # embedding model cho tính năng Hỏi đáp (RAG)
cd backend && python3 -m venv .venv && source .venv/bin/activate && pip install -e . && cd ..
cd frontend && npm install && cd ..

# Chạy — 1 lệnh, tự kiểm tra Ollama/model, khởi động backend + frontend, mở browser
./start.sh
```

Mở http://localhost:4210 → upload sách → bấm **Dịch** → theo dõi tiến độ → **Đọc**. Sách dịch xong có thêm **Tóm tắt** và **Hỏi đáp**. API docs (Swagger): http://localhost:8000/docs

<details>
<summary>Chạy thủ công từng service (không dùng <code>start.sh</code>)</summary>

```bash
# Terminal 1 — backend
cd backend && source .venv/bin/activate
uvicorn app.main:app --port 8000

# Terminal 2 — frontend
cd frontend && npm start
```

</details>

## Hướng dẫn sử dụng

**1. Thêm sách** — ở trang Thư viện, chọn ngôn ngữ đích (mặc định Tiếng Việt, hoặc chọn "Khác…" để gõ tuỳ ý), rồi bấm **Thêm sách** và chọn file. Không cần chọn ngôn ngữ gốc — ứng dụng tự nhận diện sau khi trích xuất.

**2. Dịch** — bấm **Dịch** trên sách vừa thêm để bắt đầu job dịch nền. Trang tiến độ hiển thị số phần đã dịch, ETA, và có thể **Hủy** giữa chừng hoặc **Xem trước phần đã dịch** trong lúc job vẫn chạy. Nếu job kết thúc với một số phần lỗi, dùng **Thử lại phần lỗi** thay vì dịch lại từ đầu.

**3. Đọc** — trang Đọc có 3 chế độ xem (**Song ngữ**, **Bản gốc**, **Bản dịch**), nút chỉnh cỡ chữ (A−/A+), và **☰ Mục lục** để nhảy nhanh giữa các chương (nếu sách có heading). Rê chuột vào một đoạn đã dịch sẽ hiện nút ↻ để **dịch lại riêng đoạn đó** — dùng khi một chỗ nào đó dịch sai/lẫn ngôn ngữ mà không muốn dịch lại cả cuốn. Chế độ tối bật/tắt bằng nút 🌙/☀️ ở góc phải header, áp dụng cho toàn app.

**4. Tóm tắt** — vào trang **Tóm tắt** của một sách đã dịch xong, bấm **Tạo tóm tắt** để sinh tóm tắt theo từng chương (chạy nền, có thể mất vài phút với sách dài). Có thể **Tạo lại tóm tắt** bất kỳ lúc nào.

**5. Hỏi đáp** — vào trang **Hỏi đáp**, lần đầu vào sẽ tự động đánh index nội dung sách (chạy nền). Sau đó gõ câu hỏi và nhận câu trả lời stream dựa trên nội dung sách, không bịa nếu không tìm thấy thông tin liên quan. Có thể **Đánh lại index** (sau khi dịch lại nhiều đoạn) hoặc **Xoá hội thoại** để bắt đầu lại.

**6. Tải về** — nút **Tải về** xuất file `output.html` độc lập của sách, mở thẳng bằng browser mà không cần chạy app (không có nút dịch lại từng đoạn vì không có backend để gọi).

## Chạy bằng Docker

Đóng gói backend + frontend vào container; **Ollama vẫn chạy native trên máy host**, không đưa vào Docker — trên macOS, Docker Desktop chạy container trong 1 VM Linux không pass-through được Metal/GPU của Apple Silicon, nên Ollama trong container sẽ chậm đi nhiều.

```bash
ollama pull translategemma
ollama pull qwen2.5:14b-instruct-q4_K_M
ollama pull bge-m3   # embedding model cho tính năng Hỏi đáp (RAG)
ollama serve   # nếu chưa chạy sẵn

docker compose up --build   # thêm -d để chạy nền
```

Mở http://localhost:4210 như bình thường — frontend (nginx) tự proxy `/api/*` sang backend cùng origin, backend nối tới Ollama trên host qua `host.docker.internal`. Dữ liệu (`backend/data/`) được mount làm volume nên giữ nguyên giữa các lần chạy. Dừng bằng `docker compose down`.

## Cấu hình cho máy yếu hơn

Đổi `POLISH_MODEL` trong `backend/app/config.py` (nhớ `ollama pull` model mới trước):

| Cấu hình | Model | Kích thước |
|---|---|---|
| 8-16GB RAM | `qwen2.5:7b-instruct-q4_K_M` | ~4.7GB |
| ≤8GB RAM / máy rất yếu | `qwen2.5:3b-instruct-q4_K_M` | ~2GB (văn phong kém tự nhiên hơn) |

Dòng Qwen2.5 được chọn vì train đa ngôn ngữ rộng, cho văn phong tự nhiên hơn các model cùng cỡ khác. `ROUGH_MODEL` (`translategemma`, 3.3GB) đã đủ nhẹ, không cần đổi trừ khi máy dưới 8GB.

Tốc độ tham khảo trên M1/32GB: ~4-5 phút cho ~9 trang — sách dài nên để chạy qua đêm. Job dịch lưu tiến độ sau mỗi chunk nên tắt máy giữa chừng vẫn tiếp tục được từ chỗ dừng.

## Dữ liệu

Toàn bộ dữ liệu nằm ở `backend/data/` (gitignored): SQLite (`app.db`) cho trạng thái sách/job, và mỗi sách một thư mục riêng (`original.*`, `structure.json`, `glossary.json`, `output.html`). Không có gì được gửi ra ngoài máy.

`glossary.json` giữ các tên riêng đã dịch để đảm bảo nhất quán xuyên suốt cuốn sách — không có UI riêng, nhưng có thể sửa tay file này nếu muốn ép cách dịch một tên riêng cụ thể trước khi dịch lại.

## Tài liệu dự án

- [AGENTS.md](AGENTS.md) — kiến trúc, quyết định thiết kế, và quy ước cho AI agent làm việc trong repo
