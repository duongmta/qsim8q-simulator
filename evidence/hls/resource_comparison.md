# So sánh tài nguyên HLS V1-V6

Cấu hình chung: 8 qubit, Q2.30, 256 lệnh, xc7z010clg400-1, clock 10 ns, uncertainty 1 ns.

| Bản | Thay đổi | Synthesis | RTL Cosim | Slack (ns) | BRAM18K | DSP | FF | LUT | Latency 1Q | II 1Q | Latency 2Q | II 2Q |
|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| V1 | Tối ưu tự động của Vitis (pipeline_loops=64) | PASS | PASS | 0.0 | 16 | 44 | 7834 | 10492 | 7 | 7 | 3 | 3 |
| V2 | Baseline kiểm soát, tắt auto/manual pipeline | PASS | PASS | 0.0 | 16 | 48 | 7062 | 10101 | 7 | - | 3 | - |
| V3 | Pipeline thủ công, ép II=1 | PASS | PASS | -20.74 | 16 | 48 | 3005 | 10373 | 3 | 3 | 3 | 3 |
| V4 | Pipeline thủ công, để HLS chọn II | PASS | PASS | 0.0 | 16 | 44 | 7834 | 10492 | 7 | 7 | 3 | 3 |
| V5 | Hai state buffer packed ping-pong | PASS | PASS | 0.0 | 20 | 64 | 9023 | 10902 | 7 | 1 | 3 | 1 |
| V6 | Một state buffer packed in-place, II=2 | PASS | PASS | 0.0 | 16 | 48 | 7482 | 10383 | 8 | 2 | 4 | 2 |

`CHUA_CHAY` nghĩa là chưa tìm thấy report mới trong workspace chuẩn hóa; không phải lỗi thuật toán.

## Mức thay đổi tài nguyên so với V2 baseline

| Bản | Delta BRAM18K | Delta DSP | Delta FF | Delta LUT |
|---|---:|---:|---:|---:|
| V1 | +0.00% | -8.33% | +10.93% | +3.87% |
| V2 | +0.00% | +0.00% | +0.00% | +0.00% |
| V3 | +0.00% | +0.00% | -57.45% | +2.69% |
| V4 | +0.00% | -8.33% | +10.93% | +3.87% |
| V5 | +25.00% | +33.33% | +27.77% | +7.93% |
| V6 | +0.00% | +0.00% | +5.95% | +2.79% |

## Quy tắc kết luận

- Chỉ so sánh phần trăm khi cả hai phiên bản đều có report từ cùng Vitis 2026.1.
- V2 là baseline kiểm soát.
- V6 chỉ được kết luận phù hợp nhất khi C Sim/Cosim PASS, đủ tài nguyên và timing phù hợp.
- Báo cáo tài nguyên cũ của 15 qubit/Zynq-7020 không được trộn vào bảng này.
