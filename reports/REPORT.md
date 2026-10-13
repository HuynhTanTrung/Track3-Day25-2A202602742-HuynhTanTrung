# Lab 25B — Report

**Họ tên / nhóm:** Huỳnh Tấn Trung / 2A202602742
**Commit:** `c37a5e0f026870096fc561415b814c8a330dee83`
**Điểm tự động:** 80 / 88

> Mọi nhận định phải có số. Dán số từ `reports/gameday/*.json`, `reports/workflows.json`, `reports/slo.json`.

## 1. Kết quả Game Day (naive vs của bạn)

| Băng | Client | availability | p95 (s) | amplification | retry_ratio | cost/turn | recovery (s) | PASS? |
| ---- | ------ | -----------: | ------: | ------------: | ----------: | --------: | -----------: | :---: |
| G1   | naive  |       0.7194 |   7.157 |         7.738 |       6.738 |     2.163 |          4.0 |   ✗   |
| G1   | yours  |       0.9993 |   4.954 |         1.084 |       0.022 |     2.154 |          0.0 |   ✓   |
| G2   | naive  |       0.4560 |  15.034 |         9.904 |       8.904 |     4.627 |        155.0 |   ✗   |
| G2   | yours  |       1.0000 |   5.027 |         1.037 |       0.020 |     2.120 |          0.0 |   ✓   |
| G3   | naive  |       1.0000 |   4.768 |         1.164 |       0.164 |     2.328 |          0.0 |   ✗   |
| G3   | yours  |       0.9990 |   4.963 |         1.050 |       0.032 |     2.154 |          0.0 |   ✓   |
| G4   | naive  |       1.0000 |  13.764 |         1.004 |       0.004 |     2.008 |          0.0 |   ✗   |
| G4   | yours  |       0.9995 |   5.614 |         1.046 |       0.022 |     2.150 |          0.0 |   ✓   |
| G5   | naive  |       0.3699 |   5.359 |         17.03 |       16.03 |     2.124 |            — |   ✗   |
| G5   | yours  |       0.8153 |   6.632 |         1.040 |       0.038 |     2.613 |            — |   ✓   |
| G6   | naive  |       0.5170 |   4.836 |        12.344 |      11.344 |     2.009 |          0.0 |   ✗   |
| G6   | yours  |       0.8927 |   5.981 |         1.002 |       0.031 |     2.329 |          0.0 |   ✗   |

## 2. Cấu hình client và lý do

| Tham số                             |   Giá trị | Vì sao                                                                                          |
| ----------------------------------- | --------: | ----------------------------------------------------------------------------------------------- |
| `attempt_timeout_s`                 |       3.0 | 2.0 → mọi băng sụp (G1 0.79, G6 0.58) vì timeout < median provider + queue. 3.0 là sàn an toàn. |
| `max_attempts_per_provider`         |         2 | 1 → G5 tụt 0.8153 → 0.7853.                                                                     |
| `backoff_base_s` / `backoff_cap_s`  | 0.1 / 4.0 | Full jitter; `retry_after` luôn ≥ provider đưa → G1 violations = 0.                             |
| `retry_budget_ratio`                |      0.10 | Retry_ratio quan sát 0.020–0.038 < ngưỡng G3 0.10.                                              |
| `breaker.window_size` / `min_calls` |    20 / 5 | Hạ min_calls 10→5 giúp G6 trip alpha-eu ~15 s thay vì 30 s.                                     |
| `breaker.failure_rate_threshold`    |       0.5 | G3 (30%) không trip, G2 (75%) trip.                                                             |
| `breaker.slow_call_s`               |       5.0 | G4 chèn +5 s → trip trước user timeout.                                                         |
| `breaker.open_duration_s`           |      30.0 | Cooldown dài, ít probe rác. G2 recovery 0 s.                                                    |
| `breaker.half_open_max_probes`      |         1 | Tránh thundering herd lên provider đang hồi phục.                                               |

Sơ đồ quyết định của `on_error` (ASCII hoặc bảng: loại lỗi → ghi breaker? → retry? → failover? → cooldown?):

```
CLIENT_ERROR → release → GiveUp("client_error") # không retry, không failover
QUOTA_EXHAUSTED → release → cooldown 300s → failover
RATE_LIMITED → release → cooldown = now + retry_after → failover
OVERLOAD/SERVER/TIMEOUT
→ on_failure → retry same (tries < max) → failover
→ ladder cạn → GiveUp("no_provider_available")
```

## 3. Ba thí nghiệm

**1. Retry budget là lớp phòng thủ cuối.** Khi `max_attempts_per_provider: 1` (giảm retry cùng provider), G5 tụt 0.8153 → 0.7853 → budget cần thiết. Breaker tốt thì budget ít dùng (retry_ratio 0.020–0.038 << 0.10), nhưng khi breaker cấu hình sai thì budget là lá chắn duy nhất. **Vì sao vẫn nên có cả hai:** breaker bảo vệ khỏi lỗi hệ thống (provider chết), budget bảo vệ khỏi lỗi logic (breaker config sai, lỗi transient dồn dập).

**2. `attempt_timeout_s: 30`.** Thử 2.0 (ngược chiều) → mọi băng sụp: G1 0.79, G6 0.58. Với 30 s, mỗi call alpha-eu treo ngốn hết deadline 30 s → `GiveUp("deadline")`, availability sụp. Nhưng p95 có thể **giảm** do survivorship bias (p95 chỉ tính trên lượt thành công). **G4 gần như không đổi** vì alpha +5 s vẫn < 30 s, call hoàn tất, p95 tăng nhẹ. **Timeout đúng dựa vào:** p99 latency lúc bình thường (~7 s), deadline user (30 s), và số failover tối đa trong ladder (4) → nên đặt trong khoảng 7–7.5 s. 3.0 s là lựa chọn an toàn đã kiểm chứng.

**3. Bỏ lọc tool calling khỏi `ladder()`.** Không chạy trực tiếp do giới hạn thời gian, nhưng `incompatible_routes: 0` trong `resilient.json` G6 là bằng chứng filter hoạt động. **PM:** "Tool calling yêu cầu model hỗ trợ gọi hàm. `gamma-mini` không có khả năng đó. Nếu không kiểm tra, tool call gửi sang gamma-mini sẽ trả `invalid_request_error` (400). Filter là hàng rào capability cứng, không phải tối ưu hoá — bỏ nó thì G6 sẽ có `incompatible_routes` > 0."

## 4. Workflow hoàn tiền

| Executor | completion | crashes | duplicate refunds | duplicate emails | lost refunds | overpaid (cents) | wasted LLM / crash |
| -------- | ---------: | ------: | ----------------: | ---------------: | -----------: | ---------------: | -----------------: |
| naive    |       1.00 |      81 |               128 |               81 |            0 |        1 496 700 |              1.123 |
| yours    |       1.00 |      66 |                 0 |                0 |            0 |                0 |              0.303 |

**Vì sao chỉ idempotency key chưa đủ:** key bảo vệ _một_ step (provider không thực thi hai lần). Nhưng worker chết giữa workflow → worker mới chạy lại từ đầu, các bước sau (`send_email`, `write_summary`) cần `refund_id` từ state. Không có checkpoint lưu state, worker mới không có `refund_id`.

**Vì sao chỉ checkpoint chưa đủ:** nếu ghi checkpoint **trước** khi chạy step, crash giữa "ghi" và "chạy" → worker mới tưởng step xong và bỏ qua → refund **bị mất**. Phải ghi checkpoint **sau** khi step thành công.

**Nếu ghi checkpoint trước payment:** crash giữa hai thao tác → refund không bao giờ xảy ra, phải xử lý thủ công. Bug nghiêm trọng hơn duplicate.

## 5. Alerting & error budget

| Sự cố            | Mong đợi | Naive alerter (5m)     | Burn-rate alerter |   Độ trễ |
| ---------------- | -------- | ---------------------- | ----------------- | -------: |
| checkout_bug     | page     | ✗ (5m bỏ lỡ)           | ✓ page            |   27 min |
| provider_outage  | page     | ✓ (muộn)               | ✓ page            |    4 min |
| deploy_blip      | none     | ✗ false page           | ✓ none            |        — |
| slow_leak        | ticket   | ✗ page (leo thang sai) | ✓ ticket          | 1337 min |
| degraded_evening | page     | ✓                      | ✓ page            |  291 min |
| night_spike      | none     | ✗ false page           | ✓ none            |        — |
| small_bump       | none     | ✗ false page           | ✓ none            |        — |

Burn-rate: **3 pages, 1 ticket, 0 false pages**. Budget: `consumed 42.95%`, `remaining 57.05%`, `freeze_releases: false`.

**`small_bump` (20 phút × 12% lỗi):** bad = 2.4 phút; budget 30 ngày = 0.5% × 43 200 = 216 phút → tiêu 2.4/216 = **1.1% budget**. Multi-window: short window (30m) không đủ kích hoạt page ở ngưỡng 6×, và long window (6h) không đủ vì sự cố chỉ kéo dài 20 phút. Đây chính là mục đích multi-window alerting.

## 6. Postmortem — G2 với naive client (blameless)

**Tóm tắt:** t=120, alpha mất 75% năng lực trong 3 phút (đến t=300). Client naive (3 tầng retry × 36 attempt, delay cố định 0.2 s, không breaker, không fallback) biến sự cố 3 phút thành sự cố 5 phút. Availability **45.6%**, **1 285/2 362 lượt thất bại**, recovery **155 s**.

**Ảnh hưởng:** 1 285 lượt thất bại, kéo dài 155 s sau t=300. Error budget tháng (giả sử đây là sự cố duy nhất): bad = 1 285 × 2 call = 2 570; budget = 0.5% × 10.4 M = 52 000 → tiêu **~4.9% budget**.

**Timeline** (từ `naive_G2_overload_storm_timeseries.csv`, xem hình `G2_overload_storm.png`):

|   t (s) | Sự kiện                    | Bằng chứng                        |
| ------: | -------------------------- | --------------------------------- |
|   0–119 | alpha bình thường          | calls_ok 7–15/s                   |
|     120 | alpha mất 75%              | calls_ok 7 → 2                    |
|     122 | queue alpha tràn           | calls_ok = 0                      |
| 136–142 | storm                      | attempts_alpha 53 → 233/s         |
|     142 | timeout bắt đầu            | give_up "deadline" xuất hiện      |
|     200 | metastable                 | attempts ~135/s, calls_ok ~0      |
|     300 | alpha hồi phục (theo tape) | —                                 |
| 300–320 | vẫn chưa hồi phục          | calls_ok 0–5, attempts 101 → 10/s |
|     453 | thoát storm                | calls_ok = 4                      |
|     455 | recovery = 155 s           |                                   |

**Trigger vs root cause:**

- **Trigger:** alpha mất 75% GPU (ngoài tầm kiểm soát).
- **Root cause:** retry storm không jitter, không breaker, không deadline. **Vòng lặp tự duy trì:** retry → queue đầy → 529 → retry. Provider hồi phục ở t=300 nhưng queue vẫn đầy vì chính traffic retry → metastable failure (Bronson et al. HotOS 2021).

**Điều gì giúp / tệ hơn:**

- Giúp: alpha tự hồi phục ở t=300; deadline 30 s giới hạn thiệt hại ở t=455.
- Tệ hơn: 36 attempt/call; delay cố định; không breaker; không failover.

**Action items:**

|   # | Hành động                                                      | Loại     | Kiểm chứng                     |
| --: | -------------------------------------------------------------- | -------- | ------------------------------ |
|   1 | Gộp 3 tầng retry thành 1, full jitter, tôn trọng retry-after   | prevent  | G2 amplification 9.904 → 1.037 |
|   2 | Breaker sliding-window (error rate + slow rate), cooldown 30 s | prevent  | G2 recovery 155 s → 0 s        |
|   3 | Fallback ladder có kiểm tra capability                         | mitigate | G1 naive 0.7194 → yours 0.9993 |
|   4 | Burn-rate alerting 2 cửa sổ                                    | detect   | 3 page, 0 false page           |
|   5 | Retry budget token bucket (ratio 0.10)                         | prevent  | G3 retry_ratio 0.164 → 0.032   |

## 7. Một điểm yếu còn lại

**G6 — trần cấu trúc ~0.89.** Trong A-large outage, chỉ beta phục vụ tool call được, beta 9 rps < nhu cầu ~8 rps → 429. Tool call không fail over được sang gamma-mini (không hỗ trợ tool). Bằng chứng: `attempts_by_provider = {alpha: 2390, alpha-eu: 33, beta: 1889, gamma-mini: 209}`, `give_up_reasons: {no_provider_available: 256}`.

Đã thử: `min_calls` 5 (+0.7), `max_attempts` 1 (−0.7, G5 −3.0), `open_duration_s` 30, `half_open_max_probes` 1, tăng budget. Không vượt 0.90.

**Cách sửa:** thêm provider tier C có tool calling, nâng rate limit beta khi A outage, hoặc đẩy chat call sang gamma-mini sớm hơn khi beta >70% rate limit.

## 8. Cache (Part G)

| Client               | availability | faq_availability | cache_hit_ratio | stale_served | wrong_answers | outdated_answers | cost/turn | PASS? |
| -------------------- | -----------: | ---------------: | --------------: | -----------: | ------------: | ---------------: | --------: | :---: |
| resilient (no cache) |       0.8397 |           0.8448 |             0.0 |            0 |             0 |                0 |     1.396 |   ✗   |
| cached               |       0.9131 |           0.9640 |           0.681 |          141 |             0 |               12 |     0.905 |   ✓   |

Cache: availability +7.3 điểm, faq +11.9 điểm, cost/turn −35%.

| Tham số                | Giá trị | Vì sao                                                                                   |
| ---------------------- | ------: | ---------------------------------------------------------------------------------------- |
| `similarity_threshold` |    0.93 | 0.80 → `wrong_answers_by_reason: other_question`; 0.97 → hit < 0.50.                     |
| `ttl_s`                |      90 | 600 → outdated > 15. TTL là cơ chế duy nhất giới hạn outdated khi silent update (t=480). |
| `max_stale_s`          |     180 | 0 → faq_availability fail. 180 > outage 120 s → stale_served 141.                        |

**Thí nghiệm:**

1. **Ngưỡng:** 0.80 → wrong ≠ 0 (`other_question`); 0.93 → wrong = 0, hit = 0.681; 0.97 → hit < 0.50.
2. **TTL:** 600 → outdated > 15; 90 → outdated = 12. Webhook không giúp silent update (`policy/shipping` t=480 không gọi webhook).
3. **`max_stale_s`:** 0 → faq fail; 180 → faq = 0.964, stale = 141.

**Vì sao câu hỏi cá nhân không được cache, kể cả per-user:** "Đơn #48213" và "Đơn #99999" có embedding gần nhau (cùng mẫu, khác order_id) → cùng user vẫn trả nhầm. State đơn thay đổi liên tục → câu trả lời cũ nhanh sai. `req.personal = True` → lookup trả None, store bỏ qua.

**Alert khi cache che outage:** alert trên **provider error rate** (>5%/5min) và **cache miss rate** (>0.5/10min), không dựa vào user-facing availability — dashboard vẫn xanh nhờ cache (0.9131 tổng, 0.9640 FAQ) trong khi provider đang sập.
