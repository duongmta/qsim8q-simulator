# Thực nghiệm chuyên đề 3: Qiskit BackendV2 ↔ lõi mô phỏng C/C++

Bộ thực nghiệm nối lớp `QSim8Backend` (Qiskit BackendV2) với lõi `hls/qsim8.cpp`
được biên dịch như thư viện C++ thông thường (kiểu `ap_fixed` mô phỏng chính xác bit).
Mọi yêu cầu/phản hồi đi qua khung Q8PK v1 (header + payload + CRC32), phản hồi được
giải mã bằng chính `qsim8_backend/protocol.py`. Không dùng cổng COM, bo mạch hay công cụ FPGA.

Chạy: nhấp đúp `RunChuyenDe3.cmd` ở thư mục gốc project. Kết quả: `results/chuyen_de_3/<thời điểm>/`.

- `core_service.cpp`: điểm vào `q8_service()` nhận một khung, kiểm tra, gọi `qsim8()`, trả khung phản hồi.
- `local_transport.py`: transport cùng giao diện với `Board`, nạp thư viện qua `ctypes`.
- `run_cd3.py`: kiểm thử từ chối, 15 ca bắt buộc + 3 ca stress so với Aer, lưới 8×5 đo thời gian theo
  từng chặng, kích thước khung, pytest.
- `ap_types/`: thư viện kiểu số nguồn mở của AMD/Xilinx (Apache-2.0).
