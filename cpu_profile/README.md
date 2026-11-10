# Profiling CPU QSim8Q

Bộ công cụ này đo lõi state-vector C++ FP32 độc lập. Nó không mở COM, không
nạp bo và không đưa thời gian Qiskit, Python, UART hoặc ghi tệp vào số đo.

## Chạy nhanh để kiểm tra

```powershell
# Mở PowerShell tại thư mục gốc của repository đã tải về.
.\RunCpuProfile.cmd --quick
```

Lần chạy nhanh chỉ kiểm tra compiler, logic đo, đối chiếu Qiskit và sinh báo
cáo. Không dùng số liệu quick làm kết quả chính thức.

## Chạy đầy đủ để đưa vào báo cáo

Đóng các chương trình nặng không cần thiết, cắm nguồn AC và chạy:

```powershell
# Mở PowerShell tại thư mục gốc của repository đã tải về.
.\RunCpuProfile.cmd
```

Mặc định mỗi pha có 20 mẫu, 3 warm-up và batch tự tăng đến ít nhất 10 ms. Có
thể đặt lại khi cần. Tiến trình C++ mặc định được ghim vào CPU logic 4 để máy
có kiến trúc P/E core không chuyển workload giữa hai loại lõi:

```powershell
.\RunCpuProfile.cmd --samples 30 --warmup 5 --min-batch-ms 10
```

Chỉ dùng `--affinity-cpu -1` khi muốn tắt ghim CPU và ghi rõ thay đổi đó trong
báo cáo.

Kết quả nằm trong `results/cpu_profiling/<timestamp>_full`. Mở nhanh:

```text
results/cpu_profiling/latest_report.md
```

## Chạy trong VS Code

1. Mở thư mục gốc của repository đã tải về bằng **File → Open Folder**.
2. Mở file `cpu_profile/run_cpu_profile.py` để thấy mã đang chạy.
3. Mở terminal tích hợp của VS Code và chạy `.\RunCpuProfile.cmd --quick`
   hoặc `.\RunCpuProfile.cmd`.
4. Mở `results/cpu_profiling/latest_report.md` sau khi hoàn tất.

## Phạm vi số đo

- `execute`: chạy toàn bộ danh sách native instruction.
- `kernel_1q`: chỉ các lệnh H/X/Y/Z/S/T/RX/RY/RZ của cùng mạch.
- `kernel_2q`: chỉ các lệnh CNOT/CZ; SWAP đã phân rã thành ba CNOT.
- `dispatch`: đọc và phân loại lệnh, không chạy kernel.
- `reset`, `copy`: chi phí biên, báo riêng và không cộng vào `execute`.

Tỷ lệ 1Q/2Q/dispatch trong báo cáo là ước lượng từ các phép đo tách pha. Đây
không phải tỷ lệ lấy từ Python sampling profiler.

## Tính đúng và khả năng truy nguyên

Python tạo đúng ma trận mạch bằng `benchmark_scaling.make_scaling_circuit`,
transpile với BackendV2 ở `optimization_level=0`, seed 1729, rồi xuất native
instruction và state-vector Qiskit. Chương trình C++ chạy FP32 và đối chiếu có
loại global phase. `manifest.json` lưu compiler, CPU, cấu hình và SHA-256 mã.

`std::complex<float>` được dùng để đại diện baseline CPU. Không dùng thời gian
C Simulation của `ap_fixed` làm thời gian CPU vì đó là chi phí mô phỏng kiểu dữ
liệu HLS trên máy tính.
