# Task List — Backlog cải tiến (9 việc)

Theo thứ tự đã lên plan (xem `/Users/qtang/.claude/plans/temporal-weaving-rabin.md`). Làm xong 1 việc, tick vào đây, rồi hỏi trước khi làm tiếp.

- [x] **#7 Race condition khi tạo job trùng** — `asyncio.Lock` theo `book_id` trong `job_runner.py`, bọc quanh check+insert trong `jobs.py` và `summaries.py`.
- [x] **#6 ETA trên trang tiến độ** — tính tốc độ chunk/giây từ lịch sử poll trong `job-progress-page.ts`, hiển thị "Còn khoảng ~X phút". Thuần frontend.
- [x] **#3a Test coverage: pdf_extract.py + structure.py** — `test_pdf_extract.py` (flags decode, hyphenation, image bytes), `test_structure.py` (heading/code/verse classification, header/footer filter, page-number filter, ranh giới verse vs wrapped-prose).
- [x] **#3b Test coverage: translate.py + job_runner.py** — helper `FakeOllama` mock `ollama_client.chat`. `test_translate.py` (split_paragraphs, new_capitalized_terms, fallback chain). `test_job_runner.py` (resume logic, thứ tự 2 giai đoạn, loại chunk lỗi khỏi polish).
- [x] **#4 Giới hạn upload + lỗi PDF rõ ràng** — `MAX_UPLOAD_BYTES` trong `config.py`, check size trong `books.py` (413). Check `doc.is_encrypted` trong `pdf_extract.py`, raise lỗi tiếng Việt rõ ràng.
- [x] **#1 Nút hủy job** — `POST /api/jobs/{id}/cancel` gọi `task.cancel()`. Nút "Hủy" trong `job-progress-page` với confirm dialog.
- [x] **#5 Glossary có thể sửa từ UI** — `PUT /api/books/{id}/glossary` ghi đè `glossary.json`. UI editable table + nút Lưu + ghi chú rõ chỉ ảnh hưởng phần dịch sau.
- [x] **#2 Mục lục điều hướng trang đọc** — `html_render.py` thêm `id="block-{id}"`. `GET /api/books/{id}/chapters`. Sidebar chương trong `reader-page` với scroll-to-anchor.
- [x] **#8 Dark mode / cỡ chữ** — dark mode áp dụng toàn app (không chỉ trang đọc) qua `ThemeService` + CSS variable override; cỡ chữ riêng cho trang đọc. Làm riêng cho `book.html.jinja2` (JS thuần) và Angular (`ThemeService`/`reader-page`) như dự kiến; cả 2 đều lưu `localStorage` độc lập.
- [x] **#9 Dọn CSS trùng lặp** — chuyển tất cả component styles sang SCSS, thêm bộ CSS variable dùng chung (`styles.scss`), đồng bộ cùng bảng token sang `book.html.jinja2` (plain CSS variables, không SCSS vì không có build step). Chuẩn bị sẵn cho #8 (dark mode).

## Chat hỏi-đáp về nội dung sách (RAG)

Theo plan tại `/Users/qtang/.claude/plans/temporal-weaving-rabin.md`. Làm xong 1 bước, tick vào đây, hỏi trước khi làm tiếp.

- [x] **RAG #1**: Pull `bge-m3` + thêm `embed()` vào `ollama_client.py`, verify bằng script thật.
- [x] **RAG #2**: Thêm `numpy` + viết `rag.py` (`build_index`/`load_index`/`retrieve`), test với `BookStructure` giả.
- [x] **RAG #3**: `run_index_job` + `POST /index` + `GET /index-status`, verify qua `/docs` với sách ngắn đã dịch.
- [x] **RAG #4**: `POST /chat/messages` chặn (chưa streaming), chỉnh `top_k`/similarity threshold qua `/docs`.
- [x] **RAG #5**: Chuyển sang streaming (`chat_stream()` + `StreamingResponse`), verify bằng `curl -N`.
- [x] **RAG #6**: Trang chat Angular (`fetch()`+`ReadableStream`), verify qua Preview tool.
- [x] **RAG #7**: Test với sách dài thật (600+ trang) — thời gian index + chất lượng trả lời.

## Sửa lỗi + cải tiến sau khi dùng thử

Làm xong 1 việc, tick vào đây, hỏi trước khi làm tiếp.

- [x] **Fix #1**: Lỗi dịch lẫn ngôn ngữ khác (VD: ra tiếng Tây Ban Nha thay vì tiếng Việt) — siết prompt + giảm temperature ở `translate.py` (rough + polish), giống cách đã sửa cho chat.
- [x] **Fix #2**: Tự động đánh index sau khi dịch xong — bỏ nút "Đánh index" thủ công, chain job index ngay sau khi job dịch thành công (giống cách HTML được render tự động).
- [x] **Fix #3**: Trang chat — hiển thị rõ trạng thái "đang xử lý" khi chờ trả lời, và render markdown trong câu trả lời: code block có syntax highlight, công thức toán có highlight/render riêng.
- [x] **Fix #4**: Trang đọc hiện dấu `**` thô trong tiêu đề chương (model dịch chèn markdown bold dù trang đọc không parse markdown) — siết prompt + thêm bước strip markdown artifact sau khi dịch (rough + polish).
- [x] **Fix #5**: Bỏ trang/tính năng "Giải nghĩa" (tạo quá nhiều thuật ngữ, quá tải thông tin) — xoá trang Angular, route, link, endpoint `GET`/`PUT /glossary`. Giữ nguyên cơ chế trích xuất thuật ngữ ngầm bên trong (`translate.py`) để đảm bảo dịch nhất quán tên riêng, chỉ bỏ phần hiển thị/chỉnh sửa cho người dùng.
- [x] **Fix #6**: Tổng quát hoá ngôn ngữ nguồn/đích — bỏ giới hạn `en`/`fr`→Tiếng Việt cứng. Ngôn ngữ nguồn nhập tự do khi upload, ngôn ngữ đích chọn theo từng sách (mặc định Tiếng Việt). Tham số hoá toàn bộ prompt dịch/tóm tắt/chat theo `source_lang`/`target_lang`. Verify sống bằng dịch Anh→Nhật qua toàn bộ pipeline (dịch, auto-index, chat, tóm tắt) — không chỉ mock.
- [x] **Fix #7**: Ngôn ngữ đích chuyển thành dropdown chọn sẵn (11 ngôn ngữ phổ biến + "Khác…") thay vì nhập tự do — người dùng không biết gõ đúng ra sao.
- [x] **Fix #8**: Ngôn ngữ nguồn chuyển sang tự động nhận diện — bỏ hẳn ô nhập, backend detect ngay sau khi extract PDF (dùng rough model), cache lại để không detect lại khi retry/dịch lại.
- [x] **Fix #9** (phát hiện trong lúc test Fix #8): qwen2.5 (polish model) có lỗi tái lập được — "suy nghĩ thành lời" bằng tiếng Trung khi polish văn xuôi tự sự (không liên quan gì đến ngôn ngữ nguồn/đích, tái hiện cả với Anh→Việt thuần). Đã sửa bằng retry (tối đa 3 lần) + fallback về bản rough sạch nếu vẫn lỗi — cùng kiểu xử lý với `_split_or_fallback` đã có sẵn trong code. Verify sống: câu lỗi 15/15 lần thử thô vẫn cho kết quả sạch 100% tới người dùng nhờ fallback.
