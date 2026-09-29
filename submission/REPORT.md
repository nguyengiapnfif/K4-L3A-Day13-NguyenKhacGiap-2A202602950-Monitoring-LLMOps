# Báo cáo cá nhân — K4-L3A Day 13 Monitoring & LLMOps

> Mỗi học viên hoàn thiện một file duy nhất này. Khi dẫn evidence, dùng đường dẫn tương đối, ví dụ `evidence/07-trace-waterfall.png`.

## 1. Thông tin học viên

- **Họ và tên: Nguyễn Khắc Giáp**
- **MSSV: 2A202602950**
- **Lớp:** K4-L3A
- **Repository URL: https://github.com/nguyengiapnfif/K4-L3A-Day13-NguyenKhacGiap-2A202602950-Monitoring-LLMOps**
- **Commit SHA cuối:**
- **Challenge ID:**
- **Tên project Langfuse cá nhân:** `day13-k4-l3a-2a202602950`

## 2. Evidence index

Điền đúng đường dẫn tới evidence thực tế. Có thể đổi tên hoặc dùng nhiều ảnh nếu cần.

| Evidence | Đường dẫn |
|---|---|
| Pytest cuối | `evidence/01-pytest.png` |
| Log validator | `evidence/02-log-validator.png` |
| Dashboard validator | `evidence/03-dashboard-validator.png` |
| Structured log | `evidence/04-structured-log.png` |
| PII redaction | `evidence/05a-pii-input.png` (input có PII giả), `evidence/05b-pii-redacted-log.png` (log `req-b8eb9b9a` đã che) |
| Trace list | `evidence/06-trace-list.png` |
| Trace waterfall | `evidence/07-trace-waterfall.png` (trace `4a12c6fdb0048f9cc931bfb7fe915b6f`, log `req-b8eb9b9a`) |
| Trace metadata | `evidence/08-trace-metadata.png` |
| Prompt versions | `evidence/09-prompt-versions.png` |
| Prompt rollback | `evidence/10-prompt-rollback.png` |
| Dashboard runtime | `evidence/11-dashboard-overview.png` |
| Incident metric | `evidence/12-incident-metric.png` |
| Incident log | `evidence/13-incident-log.png` |
| Incident trace | `evidence/14-incident-trace.png` |

## 3. Kết quả kỹ thuật

| Nội dung | Baseline | Kết quả cuối | Nhận xét |
|---|---|---|---|
| `validate_logs.py` | 30/100 | 100/100 | Baseline: 20/21 bản ghi thiếu `correlation_id` và context, 0 correlation ID. Sau CP1: 21 bản ghi, 10 correlation ID, không thiếu field. |
| `validate_dashboard.py` | 6/6 | 6/6 | Validator chỉ kiểm tra contract YAML; dashboard runtime làm ở CP2. |
| `pytest` | 22 passed | 39 passed | Thêm test cho PII (CCCD, thẻ, hộ chiếu), correlation ID/enrichment và cấu trúc trace. |
| Số traces hợp lệ | 0 | 10 | Baseline có 10 traces nhưng `correlation_id=MISSING` nên không nối được với log. Sau CP1: session `s01`–`s10`, đủ root/retrieval/generation. |
| Số PII leak | 0 | 0 | Baseline đã 0 vì `summarize_text` scrub preview; sau CP1 scrub mọi field của log. Trace: input/output được scrub và có hook `mask_otel_spans`. |
| Latency P95 / TTFT P95 | 583 ms / 50 ms | 615 ms / 50 ms | P95 bị kéo lên bởi request đầu tiên (fetch prompt từ Langfuse, sau đó cache 60s); P50 là 255/259 ms. Tính từ `latency_ms`, `ttft_ms` trong log, 10 request mỗi lần. |
| Retrieval success rate | 100% (10/10) | 100% (10/10) | Chưa bật incident. |

_Cột "Kết quả cuối" hiện là số đo sau CP1 (15:44 ngày 29/09/2026, giờ Việt Nam); cần chạy lại trên commit cuối trước khi nộp._

## 4. Logging và PII

- **Cách tạo/nhận và truyền correlation ID:** `CorrelationIdMiddleware` ([app/middleware.py](../app/middleware.py)) xóa structlog contextvars ở đầu mỗi request, dùng lại `x-request-id` nếu đúng format `req-<8-hex>`, ngược lại sinh `req-` + 8 ký tự hex từ `uuid4`. Header sai format (ví dụ chứa email) bị thay bằng ID mới để giá trị lạ không đi vào log hoặc trace. ID được bind vào contextvars nên mọi log trong request tự có `correlation_id`; ID cũng được truyền vào `LabAgent.run` để ghi vào trace metadata và được trả lại qua header `x-request-id` cùng `x-response-time-ms`.
- **Các metadata được ghi vào structured log:** mọi bản ghi có `ts`, `level`, `service`, `event`, `correlation_id`; request `/chat` được bind thêm `user_id_hash` (SHA-256, 12 ký tự đầu), `session_id`, `feature`, `model`, `env` trước `request_received` ([app/main.py](../app/main.py)). `response_sent` có thêm `latency_ms`, `ttft_ms`, `tokens_in`, `tokens_out`, `cost_usd`, `quality_score`, `tool_name`, `tool_success`; `request_failed` có `error_type`.
- **Cách bảo đảm PII được scrub trước khi ghi:** processor `scrub_event` ([app/logging_config.py](../app/logging_config.py)) được đăng ký sau `format_exc_info` và trước `JsonlFileProcessor`/`JSONRenderer`, nên cả traceback cũng được scrub trước khi ghi file hoặc stdout. Processor quét đệ quy mọi field chuỗi (kể cả `session_id`, `feature` do client gửi), không chỉ `payload`. Pattern trong [app/pii.py](../app/pii.py): email, số điện thoại Việt Nam, CCCD, thẻ, hộ chiếu. Log chỉ ghi preview đã scrub (tối đa 80 ký tự) và user ID dạng hash.
- **Cách kiểm chứng kết quả:** `python scripts/validate_logs.py` đạt 100/100 với 0 PII leak; sample query chứa email/số điện thoại/thẻ xuất hiện trong log dưới dạng `[REDACTED_EMAIL]`, `[REDACTED_PHONE_VN]`, `[REDACTED_CREDIT_CARD]`. Tests: [tests/test_pii.py](../tests/test_pii.py), [tests/test_correlation_logging.py](../tests/test_correlation_logging.py).

## 5. Tracing và prompt versioning

- **Cách xác nhận traces do chính tôi tạo trong project cá nhân:** traces nằm trong project `day13-k4-l3a-2a202602950` (key riêng trong `.env`, không commit), được tạo bằng `python scripts/load_test.py` lúc 15:44 ngày 29/09/2026 (giờ Việt Nam), session `s01`–`s10`; `correlation_id` của mỗi trace khớp với một request trong `data/logs.jsonl`.
- **Cấu trúc root/retrieval/generation observations:** root `lab-agent-run` (type `agent`, trace name `day13-agent-request`) có input/output là câu hỏi/câu trả lời đã scrub và metadata prompt name/label/version/source. Hai observation con: `retrieve-context` (type `retriever`: query, documents, `matched_topic`, `doc_count`) và `generate-answer` (type `generation`: model `claude-sonnet-4-5`, usage input/output, cost, `completion_start_time` để Langfuse tính TTFT, link tới prompt). `user_id` (hash), `session_id`, `environment`, tags và metadata được gắn cho cả trace qua `propagate_attributes` ([app/agent.py](../app/agent.py), [app/mock_rag.py](../app/mock_rag.py), [app/mock_llm.py](../app/mock_llm.py)).
- **Cách nối trace với log:** `correlation_id` được ghi vào metadata của trace và có trên cả ba observation. Ví dụ: log `req-5f95670d` ↔ trace `46a7ada66b50d3ba944141197685bcf6`; log `req-b8eb9b9a` ↔ trace `4a12c6fdb0048f9cc931bfb7fe915b6f` (cùng cost `$0.002721` và TTFT 50 ms ở cả log lẫn generation).
- **Prompt name:** `day13-chat`
- **Version/label baseline:**
- **Version/label candidate:**
- **Trace ID của mỗi version:**
- **Cách promote và rollback `production`:**

## 6. Dashboard, SLO và alerts

- **Dashboard và sáu panel:**
- **SLO và lý do chọn:**
- **Cách tính error budget:**
- **Ba alert và runbook tương ứng:**

## 7. Điều tra challenge

- **Challenge ID:**
- **Khoảng thời gian điều tra:**
- **Triệu chứng từ metrics:**
- **Log line và correlation ID liên quan:**
- **Trace ID và span gây ảnh hưởng:**
- **Root cause:**
- **Fix action:**
- **Preventive measure:**

## 8. Giải thích và tự đánh giá

- **Một quyết định kỹ thuật quan trọng và lý do:**
- **Một lỗi/blocker đã gặp:**
- **Cách tìm nguyên nhân và xử lý:**
- **Cách hiểu luồng Metrics → Logs → Traces:**
- **Vai trò của prompt version, token/cost, SLO hoặc rollback trong vận hành LLM:**
- **Điều quan trọng nhất đã học:**
- **Hạn chế hoặc phần chưa hoàn thành, nếu có:**

## 9. Checklist trước khi nộp

- [ ] Kết quả và evidence thuộc commit SHA cuối.
- [ ] Tất cả ảnh/output mở được bằng đường dẫn tương đối.
- [ ] Incident evidence nối đúng metric → log → trace.
- [ ] Trace/prompt evidence thuộc project Langfuse cá nhân và ảnh không lộ key/secret.
- [ ] Repository chạy lại được theo README.
- [ ] Không có secret, API key, PII thô hoặc evidence của người khác/lớp khác.
- [ ] URL repo và commit SHA cuối đã được nộp trên LMS/Codelabs.
