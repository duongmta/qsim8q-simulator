# QSim8Q: bộ mô phỏng mạch lượng tử 1–8 qubit

QSim8Q mô phỏng State-vector của mạch lượng tử bằng lõi C++ kiểu số Q2.30 và cung cấp giao diện Qiskit `BackendV2`. Ví dụ mặc định chạy **trên máy tính**, không cần FPGA, cổng COM hoặc dịch vụ web. Mã HLS, chương trình kiểm thử và dữ liệu kết quả được cung cấp để nghiên cứu và tái lập.

**Bắt đầu:** đọc [Hướng dẫn cài đặt và sử dụng](HUONG_DAN_CAI_DAT_VA_SU_DUNG.md). Trên Windows 11, cài Python 3.12 64 bit, mở PowerShell tại thư mục vừa tải về và chạy:

```powershell
& .\SetupEnvironment.cmd
& .\RunLocalDemo.cmd --circuit bell
& .\RunLocalDemo.cmd --circuit ghz8
& .\.venv\Scripts\python.exe -m pytest -q tests
```

Để chạy đầy đủ 15 ca bắt buộc, 3 ca stress và lưới 40 cấu hình, dùng `& .\RunLocalValidation.cmd`. Các ca này dùng thư viện C++ cục bộ (`execution_source=injected_transport`); chúng không phải kết quả đo trên bo.

Lõi hỗ trợ H, X, Y, Z, S, T, RX, RY, RZ, CNOT, CZ; SWAP được phân rã thành ba CNOT. Giới hạn là 1–8 qubit, 20 lớp logic và 256 lệnh native. Không hỗ trợ phép đo, reset, nhiễu hoặc `shots`.

Mã do dự án công bố theo [Apache License 2.0](LICENSE). Thành phần bên thứ ba được ghi riêng tại [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md). Tệp `ap_types/` giữ nguyên giấy phép Apache-2.0 của Xilinx.

Danh sách SHA-256 của các tệp được công bố nằm tại [MANIFEST_SHA256.csv](MANIFEST_SHA256.csv); môi trường `.venv` và tệp tạm không nằm trong danh sách này.
