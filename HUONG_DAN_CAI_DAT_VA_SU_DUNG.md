# Hướng dẫn cài đặt và sử dụng QSim8Q

## 1. Phần mềm này làm gì?

QSim8Q nhận một mạch lượng tử, biến các cổng thành danh sách lệnh native và tính State-vector cuối bằng lõi C++ Q2.30. Giao diện `QSim8Backend` tuân theo Qiskit `BackendV2`; ví dụ cục bộ dùng `LocalCoreTransport` để gọi lõi C++ trong cùng máy. Không cần bo mạch để chạy hướng dẫn này.

Thư mục tải về đã chứa mã nguồn, thư viện `q8core.dll` cho Windows x64, bộ kiểm thử và dữ liệu kết quả. Không có môi trường Python `.venv` đi kèm: mỗi người dùng tự tạo môi trường trên máy của mình.

## 2. Tải về và yêu cầu hệ thống

Trên trang GitHub của repository, chọn **Code → Download ZIP**, giải nén vào vị trí bất kỳ; hoặc dùng **Code → HTTPS** để sao chép địa chỉ và chạy `git clone <địa-chỉ-đã-sao-chép>`. Tên thư mục và ổ đĩa không ảnh hưởng đến các lệnh bên dưới.

- Windows 11 64 bit và PowerShell.
- Python 3.12 64 bit, có Python Launcher `py`. Nếu không có launcher, đặt `QSIM8_BASE_PYTHON` tới `python.exe` 3.12 trước khi cài.
- Kết nối mạng để cài các gói Python lần đầu, hoặc bộ wheel tương ứng có sẵn.
- Không cần Vitis/Vivado cho ví dụ và kiểm thử phần mềm. Vitis HLS 2026.1 chỉ cần khi muốn tự chạy lại C Simulation, C Synthesis hoặc C/RTL Co-simulation.
- Trình biên dịch `g++` chỉ cần khi muốn **tự biên dịch lại** `q8core.dll` hoặc chạy CPU profiling. DLL đã kèm theo để chạy ví dụ ngay sau khi cài Python.

Mở PowerShell **trong chính thư mục vừa giải nén hoặc clone**. Trong Windows Explorer có thể nhấp phải vào khoảng trống của thư mục và chọn **Open in Terminal**. Các lệnh tiếp theo giả định PowerShell đang ở thư mục gốc của repository.

## 3. Cài đặt

```powershell
& .\SetupEnvironment.cmd
```

Script tạo `.venv` ngay trong thư mục hiện tại, cài các gói từ `requirements.txt` và kiểm tra Qiskit/NumPy. Dòng `SETUP_ENVIRONMENT=PASS` là dấu hiệu thành công. Nếu Python 3.12 không có launcher, dùng đường dẫn Python **trên máy của bạn**:

```powershell
$env:QSIM8_BASE_PYTHON = (Get-Command python).Source
& .\SetupEnvironment.cmd
```

Biến này chỉ áp dụng cho phiên PowerShell hiện tại. Python được trỏ tới phải là bản 3.12 64 bit. Kiểm tra môi trường sau cài:

```powershell
& .\.venv\Scripts\python.exe -m qsim8_backend.launch --check-env
```

Nếu môi trường cũ có gói không tương thích, chạy `& .\SetupEnvironment.cmd --force`. Dự án yêu cầu NumPy 2.x cùng Qiskit 2.x; không sao chép `.venv` từ máy khác.

## 4. Chạy ví dụ

```powershell
& .\RunLocalDemo.cmd --circuit bell
& .\RunLocalDemo.cmd --circuit ghz8
```

Ví dụ tạo mạch trong Qiskit, biên dịch theo tập cổng của backend, gửi khung Q8PK qua `LocalCoreTransport` đến `q8core.dll`, rồi so State-vector nhận được với Qiskit. Kết quả in `Emax`, fidelity, `Enorm` và `LOCAL_CORE_DEMO=PASS`. Dòng `execution_source=injected_transport` có nghĩa là chạy trong máy tính, không qua UART hay FPGA.

Mã ví dụ ở `examples/local_core_demo.py`. Qubit `q0` là bit thấp nhất trong chỉ số State-vector.

## 5. Chạy kiểm thử

Bộ test tự động, không mở cổng COM:

```powershell
& .\.venv\Scripts\python.exe -m pytest -q tests
```

Bộ đánh giá cục bộ đầy đủ:

```powershell
& .\RunLocalValidation.cmd
```

Lần chạy đầy đủ kiểm tra 15 ca bắt buộc, 3 ca stress, 40 cấu hình độ rộng/số lớp và các test Python. Nó tạo thư mục mới trong `results/chuyen_de_3/`; đọc `status.json`, `acceptance.csv`, `scaling.csv` và `pytest.txt` **của đúng lần chạy đó**. Dòng `ACCEPTANCE mandatory 15 / 15` chỉ xác nhận lần chạy tương ứng. Dữ liệu có sẵn trong `results/` là kết quả lưu từ các lần thử trước, không phải kết quả của máy bạn.

Ngưỡng đánh giá: `Emax ≤ 1e-2`, fidelity `≥ 0.99`, `Enorm ≤ 1e-2`. Một tập test đạt không chứng minh mọi mạch có thể có đều đúng.

## 6. Tự biên dịch lại lõi C++ (tùy chọn)

`experiments/cd3_python_core/build/q8core.dll` là thư viện Windows x64 đã biên dịch. Mã nguồn tương ứng ở `hls/qsim8.cpp` và `experiments/cd3_python_core/core_service.cpp`; header Q8PK ở cùng thư mục với `core_service.cpp`. Các header mô phỏng kiểu số `ap_fixed` nằm trong `experiments/cd3_python_core/ap_types/`.

Nếu đã cài `g++` cho Windows và có trong `PATH`, chạy:

```powershell
& .\RunChuyenDe3.cmd
```

Hoặc đặt `$env:CXX` tới đường dẫn `g++.exe` của máy bạn trước khi chạy. Script biên dịch lại DLL rồi chạy bộ đánh giá. Không gọi Git Bash hay `run.sh`.

## 7. Mã HLS và dữ liệu nghiên cứu

`hls/hls_config.cfg` khai báo phần cứng đích `xc7z010clg400-1`, top `qsim8` và clock mục tiêu 10 ns. Các báo cáo HLS đã lưu ở `evidence/hls/`. Sáu phương án khảo sát HLS ở `research/hls_v1_v6/`; xem README ngay trong thư mục đó để hiểu từng phương án. V6 là một điểm nghiên cứu, không phải chứng minh tối ưu toàn cục.

Muốn tự chạy **chỉ C Simulation**, mở PowerShell tại thư mục gốc, chọn một `work_dir` mới chưa tồn tại và dùng `vitis-run.bat` của Vitis HLS 2026.1 trên máy bạn:

```powershell
if (-not $env:XILINX_VITIS) { throw 'Đặt XILINX_VITIS tới thư mục Vitis 2026.1' }
$vitisRun = Join-Path $env:XILINX_VITIS 'bin\vitis-run.bat'
if (-not (Test-Path -LiteralPath $vitisRun)) { throw 'Đặt XILINX_VITIS tới thư mục Vitis 2026.1' }
Set-Location .\hls
$work = Join-Path (Get-Location) 'work_csim_moi'
if (Test-Path -LiteralPath $work) { throw 'Chọn tên work_dir mới' }
& $vitisRun --mode hls --csim --config '.\hls_config.cfg' --work_dir $work
```

Chỉ kết luận CSim đạt khi lệnh trả mã 0, báo cáo CSim báo không có lỗi và testbench báo `PASS` với `failures=0`. C Synthesis và Co-simulation là hai bước riêng. Clock mục tiêu và clock ước lượng của HLS không phải phép đo trên FPGA.

## 8. Phạm vi và giới hạn

- 1–8 qubit, tối đa 20 lớp logic, tối đa 256 lệnh native; State-vector Q2.30.
- Cổng: H, X, Y, Z, S, T, RX, RY, RZ, CNOT, CZ. SWAP được phân rã thành ba CNOT.
- Không hỗ trợ phép đo, reset, nhiễu, mạch động hoặc `shots`.
- Kết quả `injected_transport` là phần mềm cục bộ. Không suy ra thời gian hay mức tăng tốc FPGA từ các kết quả này.

## 9. Xử lý lỗi

| Hiện tượng | Cách kiểm tra |
|---|---|
| Không tìm thấy Python 3.12 | Chạy `py -3.12 --version`; cài Python 3.12 64 bit hoặc đặt `QSIM8_BASE_PYTHON`. |
| `NoneType copy mode not allowed` hoặc lỗi NumPy | Kiểm tra NumPy 2.x trong `.venv`; chạy `SetupEnvironment.cmd --force`. |
| Không nạp được `q8core.dll` | Kiểm tra đang dùng Windows/Python x64 và có tệp `experiments/cd3_python_core/build/q8core.dll`. |
| Không có `g++` | Ví dụ và pytest vẫn dùng DLL kèm theo. Để tự biên dịch, cài compiler Windows và đặt `CXX`. |
| Sai thứ tự biên độ | Kiểm tra quy ước little endian: `q0` là bit thấp nhất. |
| Mạch bị từ chối | Kiểm tra số qubit, lớp, lệnh và các cổng không hỗ trợ ở mục 8. |

## 10. Giấy phép và tính tái lập

[LICENSE](LICENSE) áp dụng cho mã do dự án công bố; [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md) ghi thành phần bên thứ ba. Các kết quả đã lưu được giữ để đối chiếu; khi báo cáo lại, ghi thời gian, môi trường và đường dẫn của lần chạy mới. Repository không yêu cầu bất kỳ thư mục cá nhân hoặc repository khác nào để chạy ví dụ và test.
