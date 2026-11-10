# Kết quả kiểm tra chức năng trước HLS

Ngày kiểm tra: 2026-09-10.

Sáu phiên bản được biên dịch độc lập bằng MinGW C++ đi kèm bộ cài Xilinx 2026.1, sử dụng `ap_int.h` và `ap_fixed.h` của Vitis. Đây là bước kiểm tra chức năng phía host trước khi chạy C Simulation/C Synthesis trong Vitis HLS.

| Bản | Số ca PASS | Emax lớn nhất | Fidelity nhỏ nhất | Enorm lớn nhất | Kết quả |
|---|---:|---:|---:|---:|---|
| V1 | 18/18 | 4.215e-08 | 1.0000000000 | 7.707e-08 | PASS |
| V2 | 18/18 | 4.215e-08 | 1.0000000000 | 7.707e-08 | PASS |
| V3 | 18/18 | 4.215e-08 | 1.0000000000 | 7.707e-08 | PASS |
| V4 | 18/18 | 4.215e-08 | 1.0000000000 | 7.707e-08 | PASS |
| V5 | 18/18 | 4.215e-08 | 1.0000000000 | 7.707e-08 | PASS |
| V6 | 18/18 | 4.215e-08 | 1.0000000000 | 7.707e-08 | PASS |

Các kết quả giống nhau là điều mong đợi: V1-V6 chỉ thay đổi chỉ thị HLS và tổ chức bộ nhớ, không thay đổi phép biến đổi lượng tử. Các log chi tiết nằm trong `reports/functional_logs`.

Kết quả này chứng minh mã C++ của sáu bản có cùng hành vi số và đều vượt ngưỡng thuyết minh:

- Emax <= 1e-2.
- Fidelity >= 0.99.
- |norm-1| <= 1e-2.

Đây chưa phải bằng chứng RTL hoặc tài nguyên FPGA. Các kết luận BRAM/DSP/FF/LUT, latency, II và timing chỉ được ghi sau khi Vitis HLS tạo `hls_compile.rpt` và `hls_cosim.rpt` cho từng bản.

