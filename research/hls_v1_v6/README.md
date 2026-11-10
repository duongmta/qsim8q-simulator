# QSim8Q HLS V1-V6 - thí nghiệm chuẩn hóa 8 qubit / Zynq-7010

Thư mục này là bộ thí nghiệm HLS độc lập được chuẩn hóa để so sánh V1–V6 trên cùng điều kiện.

## Mục tiêu

Sáu phiên bản dùng chung:

- FPGA: `xc7z010clg400-1` của Zybo Zynq-7000.
- Clock HLS: 10 ns, uncertainty 1 ns.
- Phạm vi: 1-8 qubit, tối đa 256 amplitude.
- Tối đa 256 lệnh native.
- Kiểu số HLS: Q2.30, `ap_fixed<32,2,AP_RND_CONV,AP_SAT>`.
- Cổng native: H, X, Y, Z, S, T, RX, RY, RZ, CNOT, CZ.
- SWAP được phân rã thành ba CNOT.
- Cùng một testbench FP32 gồm 18 ca, có mạch 8 qubit sâu 20.
- Ngưỡng thuyết minh: Emax <= 1e-2, fidelity >= 0.99, |norm-1| <= 1e-2.

Mỗi phiên bản chỉ thay đổi chiến lược pipeline hoặc tổ chức bộ nhớ. Đây là điều kiện cần để số liệu tài nguyên và hiệu năng có thể so sánh trực tiếp.

## Vai trò từng phiên bản

| Bản | Thay đổi độc lập | Mục đích |
|---|---|---|
| V1 | Không có pragma pipeline thủ công; `pipeline_loops=64` | Ghi nhận thiết kế ban đầu khi dùng tối ưu tự động của Vitis HLS |
| V2 | Tắt auto-pipeline; chưa có pipeline thủ công | Baseline kiểm soát để đo chi phí và latency chưa tối ưu |
| V3 | Thêm `PIPELINE II=1` trên các vòng lặp chính | Thử tối đa thông lượng; có thể tăng DSP/LUT hoặc vi phạm timing do xung đột cổng BRAM |
| V4 | Đổi `PIPELINE II=1` thành `PIPELINE` | Cho HLS chọn II khả thi thay vì ép II=1 |
| V5 | Pack số phức 64-bit, hai BRAM `state_a/state_b`, xử lý out-of-place | Tách đọc và ghi để hướng tới II thấp; đổi lại tăng BRAM |
| V6 | Một BRAM packed true-dual-port, xử lý in-place, `DEPENDENCE inter false`, II=2 | Cân bằng tài nguyên và thông lượng; là kiến trúc được chuyển sang lõi QSim8Q cuối |

Chi tiết lập luận và cách đọc kết quả nằm tại [docs/ARCHITECTURE_EVOLUTION.md](docs/ARCHITECTURE_EVOLUTION.md). Quy trình chạy thủ công nằm tại [docs/RUN_VITIS_HLS.md](docs/RUN_VITIS_HLS.md).

## Cấu trúc

```text
research/hls_v1_v6/
├── v1/ ... v6/              mã HLS, testbench và cấu hình riêng
├── docs/                    giải thích và hướng dẫn chạy
├── scripts/                 kiểm tra cấu hình, tổng hợp và thu báo cáo
├── build/                   workspace sinh bởi Vitis HLS
└── reports/                 bảng so sánh được tạo tự động
```

## Kiểm tra nhanh bộ nguồn

```powershell
# Chạy từ thư mục gốc của repository.
& .\.venv\Scripts\python.exe .\research\hls_v1_v6\scripts\check_consistency.py
```

Lệnh này không chạy HLS. Nó xác nhận sáu bản có cùng part, clock, giới hạn qubit, kiểu Q2.30 và cùng testbench.

Bộ nguồn đã được biên dịch và kiểm tra chức năng trên host bằng compiler/header của Xilinx. Cả sáu bản đạt 18/18 ca; xem [reports/functional_precheck.md](reports/functional_precheck.md). Kết quả này chưa thay thế C Synthesis hoặc RTL Co-simulation.

## Sau khi chạy HLS

```powershell
# Chạy từ thư mục gốc của repository.
& .\.venv\Scripts\python.exe .\research\hls_v1_v6\scripts\collect_reports.py
```

Kết quả được ghi vào:

- `reports/resource_comparison.csv`
- `reports/resource_comparison.md`
- `reports/evidence_manifest.json`

Không điền số liệu ước đoán vào báo cáo. Chỉ các con số đọc từ report do Vitis 2026.1 tạo mới được coi là bằng chứng của cấu hình 8 qubit/Zynq-7010.
