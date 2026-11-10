# Báo cáo profiling CPU QSim8Q

## Phạm vi và phương pháp

Đây là bộ đo đầy đủ 1–8 qubit × depth 1/5/10/15/20 và microbenchmark.

- Lõi được đo: state-vector C++ FP32, một luồng, biên dịch Release `-O3`.
- Qiskit chỉ sinh mạch đã transpile và state-vector chuẩn trước khi đo.
- UART, web, ghi CSV và Qiskit/Aer không nằm trong vùng thời gian.
- Mỗi phép đo dùng batch tự hiệu chỉnh tối thiểu 10.0 ms, 20 mẫu và 3 warm-up.
- Tiến trình được ghim vào CPU logic 4 để tránh di chuyển giữa lõi P/E.
- `kernel_1q`, `kernel_2q` và `dispatch` được đo tách biệt; tỷ lệ hotspot là tỷ lệ ước lượng từ ba phép đo này.
- `reset` và `copy` là chi phí biên được báo riêng, không cộng vào `execute`.

## Môi trường

- CPU: 13th Gen Intel(R) Core(TM) i5-13400F
- Hệ điều hành: Windows-11-10.0.26200-SP0
- Compiler: g++.exe (Rev5, Built by MSYS2 project) 16.1.0
- Số CPU logic: 16
- UTC: 2026-09-15T07:39:18.683106+00:00

## Kiểm tra tính đúng

- Kết quả FP32 đạt so với state-vector Qiskit: **90/90** ca.
- Ngưỡng kiểm tra: `max_error ≤ 1e-5`, `fidelity ≥ 1 - 1e-7`, `norm_error ≤ 1e-5`.
- So sánh đã loại global phase trước khi tính sai số cực đại.

## Chất lượng số đo

- Robust CV lớn nhất trong 40 ca scaling: **10.58%** tại `MIXED_2Q_1L`.
- Số ca scaling có robust CV lớn hơn 10%: **1/40**.
- CV thường lớn nhất là **72.18%** tại `MIXED_2Q_1L`; giá trị này nhạy với ngắt hệ điều hành và vẫn được giữ trong CSV.
- Báo cáo dùng median làm giá trị trung tâm, robust CV đánh giá độ ổn định và p95 thể hiện nhiễu lập lịch.

## Benchmark mở rộng

| Ca | Qubit | Depth | Lệnh | Median µs | P95 µs | Robust CV % | Miter/s | Qiskit |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| MIXED_1Q_1L | 1 | 1 | 1 | 0.0050 | 0.0057 | 1.34 | 201.73 | PASS |
| MIXED_1Q_5L | 1 | 5 | 5 | 0.0210 | 0.0256 | 1.85 | 237.81 | PASS |
| MIXED_1Q_10L | 1 | 10 | 10 | 0.0419 | 0.0441 | 4.07 | 238.49 | PASS |
| MIXED_1Q_15L | 1 | 15 | 15 | 0.0665 | 0.0733 | 7.93 | 225.40 | PASS |
| MIXED_1Q_20L | 1 | 20 | 20 | 0.0879 | 0.1014 | 0.61 | 227.52 | PASS |
| MIXED_2Q_1L | 2 | 1 | 2 | 0.0121 | 0.0299 | 10.58 | 330.59 | PASS |
| MIXED_2Q_5L | 2 | 5 | 8 | 0.0419 | 0.0425 | 1.44 | 477.27 | PASS |
| MIXED_2Q_10L | 2 | 10 | 16 | 0.0783 | 0.0832 | 3.31 | 511.15 | PASS |
| MIXED_2Q_15L | 2 | 15 | 24 | 0.1220 | 0.1343 | 3.59 | 491.65 | PASS |
| MIXED_2Q_20L | 2 | 20 | 32 | 0.1785 | 0.1936 | 5.34 | 448.18 | PASS |
| MIXED_3Q_1L | 3 | 1 | 3 | 0.0181 | 0.0186 | 0.98 | 663.92 | PASS |
| MIXED_3Q_5L | 3 | 5 | 13 | 0.0915 | 0.0997 | 1.47 | 655.88 | PASS |
| MIXED_3Q_10L | 3 | 10 | 26 | 0.1985 | 0.2030 | 1.06 | 604.60 | PASS |
| MIXED_3Q_15L | 3 | 15 | 39 | 0.2818 | 0.3155 | 2.63 | 638.84 | PASS |
| MIXED_3Q_20L | 3 | 20 | 52 | 0.4002 | 0.4043 | 1.42 | 599.63 | PASS |
| MIXED_4Q_1L | 4 | 1 | 4 | 0.0355 | 0.0577 | 1.44 | 900.17 | PASS |
| MIXED_4Q_5L | 4 | 5 | 17 | 0.2005 | 0.2216 | 2.69 | 797.82 | PASS |
| MIXED_4Q_10L | 4 | 10 | 34 | 0.4386 | 0.4693 | 7.31 | 729.67 | PASS |
| MIXED_4Q_15L | 4 | 15 | 51 | 0.5921 | 0.6152 | 1.72 | 810.68 | PASS |
| MIXED_4Q_20L | 4 | 20 | 68 | 0.7807 | 0.8023 | 1.38 | 819.78 | PASS |
| MIXED_5Q_1L | 5 | 1 | 5 | 0.0601 | 0.0614 | 1.30 | 1331.10 | PASS |
| MIXED_5Q_5L | 5 | 5 | 21 | 0.4403 | 0.4472 | 1.30 | 908.50 | PASS |
| MIXED_5Q_10L | 5 | 10 | 42 | 0.9882 | 1.1321 | 7.30 | 809.54 | PASS |
| MIXED_5Q_15L | 5 | 15 | 63 | 1.3323 | 1.3512 | 1.21 | 900.71 | PASS |
| MIXED_5Q_20L | 5 | 20 | 84 | 1.8375 | 1.9832 | 2.07 | 870.74 | PASS |
| MIXED_6Q_1L | 6 | 1 | 6 | 0.1227 | 0.1292 | 3.69 | 1564.94 | PASS |
| MIXED_6Q_5L | 6 | 5 | 25 | 0.9983 | 1.0299 | 2.08 | 961.61 | PASS |
| MIXED_6Q_10L | 6 | 10 | 50 | 2.0287 | 2.0782 | 1.13 | 946.42 | PASS |
| MIXED_6Q_15L | 6 | 15 | 75 | 3.0341 | 3.0758 | 0.85 | 949.21 | PASS |
| MIXED_6Q_20L | 6 | 20 | 100 | 4.0237 | 4.2274 | 1.53 | 954.34 | PASS |
| MIXED_7Q_1L | 7 | 1 | 7 | 0.2318 | 0.2349 | 1.20 | 1932.42 | PASS |
| MIXED_7Q_5L | 7 | 5 | 29 | 2.2198 | 2.2565 | 1.17 | 1009.10 | PASS |
| MIXED_7Q_10L | 7 | 10 | 58 | 4.5164 | 4.5975 | 0.75 | 991.94 | PASS |
| MIXED_7Q_15L | 7 | 15 | 87 | 6.7317 | 6.8157 | 0.85 | 998.26 | PASS |
| MIXED_7Q_20L | 7 | 20 | 116 | 8.9788 | 9.1466 | 0.98 | 997.90 | PASS |
| MIXED_8Q_1L | 8 | 1 | 8 | 0.5243 | 0.5565 | 1.71 | 1952.91 | PASS |
| MIXED_8Q_5L | 8 | 5 | 33 | 5.0059 | 5.1442 | 1.85 | 1022.79 | PASS |
| MIXED_8Q_10L | 8 | 10 | 66 | 10.1080 | 11.5433 | 2.21 | 1013.06 | PASS |
| MIXED_8Q_15L | 8 | 15 | 99 | 16.0773 | 16.6691 | 5.46 | 955.38 | PASS |
| MIXED_8Q_20L | 8 | 20 | 132 | 20.7698 | 22.1250 | 3.14 | 986.05 | PASS |

## Hotspot

Ở ca `MIXED_8Q_20L`, tỷ lệ ước lượng là:

| Pha | Tỷ lệ |
|---|---:|
| Kernel 1Q | 83.53% |
| Kernel 2Q | 16.04% |
| Dispatch | 0.43% |

Pha lớn nhất trong ca này là **kernel 1Q**. Hệ số tương quan Pearson giữa số vòng lặp kernel theo thuật toán và thời gian `execute` của ma trận scaling là **0.999420**. Kết luận này chỉ áp dụng cho cấu hình CPU và phạm vi 1–8 qubit của lần đo.

Các vùng mã tương ứng là `apply_single_qubit_gate`, `apply_two_qubit_gate` và
`execute_circuit` trong `cpu_profile/qsim_cpu.cpp`. Mỗi cổng 1Q duyệt
`2^(n-1)` cặp amplitude; mã CPU 2Q hiện duyệt `2^n` chỉ số và cập nhật tập con
thỏa bit control/target. Đây là các vòng lặp cần đối chiếu với pipeline và tổ
chức BRAM của HLS V1–V6.

## Microbenchmark

| Ca vi mô | Lệnh | Median µs | Robust CV % | Qiskit |
| --- | ---: | ---: | ---: | --- |
| MICRO_H_1Q_q0 | 1 | 0.0045 | 1.02 | PASS |
| MICRO_RX_1Q_q0 | 1 | 0.0054 | 4.69 | PASS |
| MICRO_H_2Q_q0 | 1 | 0.0065 | 7.29 | PASS |
| MICRO_RX_2Q_q0 | 1 | 0.0077 | 2.11 | PASS |
| MICRO_H_3Q_q0 | 1 | 0.0079 | 4.44 | PASS |
| MICRO_RX_3Q_q0 | 1 | 0.0105 | 1.43 | PASS |
| MICRO_H_4Q_q0 | 1 | 0.0124 | 6.04 | PASS |
| MICRO_RX_4Q_q0 | 1 | 0.0182 | 3.21 | PASS |
| MICRO_H_5Q_q0 | 1 | 0.0245 | 6.27 | PASS |
| MICRO_RX_5Q_q0 | 1 | 0.0396 | 6.04 | PASS |
| MICRO_H_6Q_q0 | 1 | 0.0464 | 1.62 | PASS |
| MICRO_RX_6Q_q0 | 1 | 0.0709 | 1.72 | PASS |
| MICRO_H_7Q_q0 | 1 | 0.0822 | 5.39 | PASS |
| MICRO_RX_7Q_q0 | 1 | 0.1309 | 1.36 | PASS |
| MICRO_H_8Q_q0 | 1 | 0.1546 | 0.77 | PASS |
| MICRO_RX_8Q_q0 | 1 | 0.2513 | 1.39 | PASS |
| MICRO_CNOT_2Q_q0_q1 | 1 | 0.0036 | 1.07 | PASS |
| MICRO_CZ_2Q_q0_q1 | 1 | 0.0031 | 2.57 | PASS |
| MICRO_CNOT_3Q_q0_q2 | 1 | 0.0042 | 0.34 | PASS |
| MICRO_CZ_3Q_q0_q2 | 1 | 0.0041 | 0.68 | PASS |
| MICRO_CNOT_4Q_q0_q3 | 1 | 0.0132 | 3.58 | PASS |
| MICRO_CZ_4Q_q0_q3 | 1 | 0.0073 | 6.77 | PASS |
| MICRO_CNOT_5Q_q0_q4 | 1 | 0.0242 | 6.39 | PASS |
| MICRO_CZ_5Q_q0_q4 | 1 | 0.0133 | 0.86 | PASS |
| MICRO_CNOT_6Q_q0_q5 | 1 | 0.0413 | 3.92 | PASS |
| MICRO_CZ_6Q_q0_q5 | 1 | 0.0240 | 0.91 | PASS |
| MICRO_CNOT_7Q_q0_q6 | 1 | 0.0714 | 2.39 | PASS |
| MICRO_CZ_7Q_q0_q6 | 1 | 0.0395 | 2.90 | PASS |
| MICRO_CNOT_8Q_q0_q7 | 1 | 0.1082 | 3.18 | PASS |
| MICRO_CZ_8Q_q0_q7 | 1 | 0.0953 | 0.85 | PASS |
| MICRO_H_8Q_q7 | 1 | 0.0382 | 7.01 | PASS |
| MICRO_X_8Q_q0 | 1 | 0.1176 | 8.11 | PASS |
| MICRO_X_8Q_q7 | 1 | 0.0313 | 2.08 | PASS |
| MICRO_Y_8Q_q0 | 1 | 0.1568 | 3.46 | PASS |
| MICRO_Y_8Q_q7 | 1 | 0.0737 | 9.21 | PASS |
| MICRO_Z_8Q_q0 | 1 | 0.1552 | 1.76 | PASS |
| MICRO_Z_8Q_q7 | 1 | 0.0583 | 3.21 | PASS |
| MICRO_S_8Q_q0 | 1 | 0.1557 | 2.78 | PASS |
| MICRO_S_8Q_q7 | 1 | 0.0516 | 4.39 | PASS |
| MICRO_T_8Q_q0 | 1 | 0.1704 | 1.82 | PASS |
| MICRO_T_8Q_q7 | 1 | 0.0730 | 4.00 | PASS |
| MICRO_RX_8Q_q7 | 1 | 0.3339 | 26.58 | PASS |
| MICRO_RY_8Q_q0 | 1 | 0.4107 | 22.93 | PASS |
| MICRO_RY_8Q_q7 | 1 | 0.2278 | 2.25 | PASS |
| MICRO_RZ_8Q_q0 | 1 | 0.3319 | 1.98 | PASS |
| MICRO_RZ_8Q_q7 | 1 | 0.2366 | 2.21 | PASS |
| MICRO_CNOT_8Q_q0_q1 | 1 | 0.0916 | 3.18 | PASS |
| MICRO_CZ_8Q_q0_q1 | 1 | 0.0739 | 1.43 | PASS |
| MICRO_SWAP_8Q_q0_q1 | 3 | 0.3065 | 15.98 | PASS |
| MICRO_SWAP_8Q_q0_q7 | 3 | 0.3174 | 2.00 | PASS |

## Biểu đồ


![01_cpu_time_vs_qubits.png](charts/01_cpu_time_vs_qubits.png)

![02_cpu_time_vs_depth.png](charts/02_cpu_time_vs_depth.png)

![03_hotspot_share.png](charts/03_hotspot_share.png)

![04_gate_cost_8q.png](charts/04_gate_cost_8q.png)

![05_time_vs_work.png](charts/05_time_vs_work.png)


## Diễn giải cho thuyết minh

Số vòng lặp cập nhật state-vector tăng theo số lệnh và theo số amplitude. Số liệu `kernel_1q`, `kernel_2q` và `dispatch` cho biết phần nào chiếm thời gian thay vì suy luận từ mã nguồn. Đây là căn cứ nối công việc profiling CPU với các thử nghiệm PIPELINE, BRAM, dữ liệu đóng gói và Q2.30 trong HLS V1–V6.

State-vector 8 qubit FP32 chỉ có 256 số phức, khoảng 2 KiB, thường nằm trong cache L1. Kết quả không được diễn giải thành bằng chứng nghẽn DRAM ở quy mô lớn. Trên FPGA, giới hạn truy cập BRAM/II là vấn đề kiến trúc riêng được chứng minh bằng báo cáo HLS.

## Tệp dữ liệu

- `cpu_profile_raw.csv`: từng mẫu và batch repetitions.
- `cpu_profile_summary.csv`: median, p95, CV, phân bố pha và độ chính xác.
- `validation.csv`: đối chiếu FP32 với Qiskit.
- `manifest.json`: môi trường, cấu hình, lệnh biên dịch và hash mã nguồn.
- `suite.tsv`: mạch native và state-vector Qiskit đã dùng.
