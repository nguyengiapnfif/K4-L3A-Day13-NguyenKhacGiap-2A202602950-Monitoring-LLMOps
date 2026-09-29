# Alert và Runbook

Mỗi alert dựa trên triệu chứng người dùng hoặc SLO, không dựa trực tiếp vào tên implementation nội bộ. Định nghĩa máy đọc được nằm trong [`../config/alert_rules.yaml`](../config/alert_rules.yaml); SLO nằm trong [`../config/slo.yaml`](../config/slo.yaml).

Severity: **P1** = người dùng nhận lỗi, xử lý ngay; **P2** = người dùng bị chậm, xử lý trong giờ trực; **P3** = chưa ảnh hưởng trải nghiệm nhưng tốn tiền, xử lý trong ngày.

## Alert 1

- Tên: `high_latency_p95`
- Severity: P2
- Duration: 5 phút
- Kênh thông báo: Slack `#day13-k4-l3a-alerts`
- SLI/SLO liên quan: `fast_successful_requests` (99,5% request thành công trong ≤ 1500 ms, cửa sổ 28 ngày).
- Điều kiện và thời gian duy trì: P95 `latency_ms` của `response_sent` > 1500 ms liên tục 5 phút.
- Ảnh hưởng tới người dùng: câu trả lời chậm rõ rệt; mỗi request vượt 1500 ms tiêu vào error budget.
- Ba bước kiểm tra đầu tiên:
  1. **Metrics:** panel Latency: chỉ P95/P99 tăng hay cả P50 tăng? TTFT P95 có tăng không? (TTFT bình thường mà latency tăng → chậm trước bước LLM.)
  2. **Logs:** lọc `response_sent` có `latency_ms > 1500` trong khoảng sự cố, lấy vài `correlation_id`; kiểm tra các request chậm có chung `feature` hay không.
  3. **Traces:** mở trace có cùng `correlation_id` trong Langfuse, so sánh duration của `retrieve-context` và `generate-answer` để biết bước nào chậm.
- Mitigation tạm thời: nếu retrieval chậm: giảm timeout vector store và trả lời bằng fallback docs; nếu LLM chậm: chuyển sang model nhanh hơn hoặc giảm độ dài output.
- Owner: Nguyễn Khắc Giáp

## Alert 2

- Tên: `high_error_rate`
- Severity: P1
- Duration: 5 phút
- Kênh thông báo: Slack `#day13-k4-l3a-alerts`
- SLI/SLO liên quan: `fast_successful_requests`; guardrail `error_rate_pct_max: 2`.
- Điều kiện và thời gian duy trì: `request_failed / request_received × 100` > 2% liên tục 5 phút.
- Ảnh hưởng tới người dùng: người dùng nhận HTTP 500 thay vì câu trả lời; error budget bị tiêu rất nhanh.
- Ba bước kiểm tra đầu tiên:
  1. **Metrics:** panel Errors: error rate, breakdown theo `error_type` và retrieval success rate có giảm cùng lúc không.
  2. **Logs:** lọc `request_failed`, xem `error_type`, `tool_name`, `tool_success` và `payload.detail`; lấy `correlation_id` của một request lỗi.
  3. **Traces:** mở trace có cùng `correlation_id`; observation có level ERROR (ví dụ `retrieve-context` với status `Vector store timeout`) cho biết thành phần lỗi.
- Mitigation tạm thời: nếu lỗi ở retrieval: trả lời bằng fallback docs thay vì trả 500, hoặc tắt tính năng phụ thuộc vector store; nếu do deploy mới: rollback.
- Owner: Nguyễn Khắc Giáp

## Alert 3

- Tên: `cost_per_request_spike`
- Severity: P3
- Duration: 15 phút
- Kênh thông báo: Slack `#day13-k4-l3a-alerts`
- SLI/SLO liên quan: guardrail `daily_cost_usd_max: 2.5`.
- Điều kiện và thời gian duy trì: trung bình `cost_usd` mỗi `response_sent` > 0,004 USD (2 lần baseline khoảng 0,002 USD) liên tục 15 phút.
- Ảnh hưởng tới người dùng: chưa ảnh hưởng trực tiếp, nhưng nếu kéo dài sẽ vượt ngân sách ngày; output dài bất thường thường kèm chất lượng giảm.
- Ba bước kiểm tra đầu tiên:
  1. **Metrics:** panel Cost và Tokens: cost tăng do `tokens_in` (prompt/context dài) hay `tokens_out` (câu trả lời dài)?
  2. **Logs:** lọc `response_sent` có `cost_usd` cao, lấy `correlation_id`, kiểm tra `tokens_out` và `feature`.
  3. **Traces:** mở trace có cùng `correlation_id`, xem usage/cost của `generate-answer` và prompt version đang dùng (một prompt version mới có thể làm output dài hơn).
- Mitigation tạm thời: giới hạn `max_tokens` output; nếu do prompt mới, rollback label `production` về version trước.
- Owner: Nguyễn Khắc Giáp
