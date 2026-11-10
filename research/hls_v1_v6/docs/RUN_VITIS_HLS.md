# Hướng dẫn chạy Vitis HLS 2026.1

## 1. Điều kiện cần giữ nguyên

Khi tạo component cho mỗi phiên bản, kiểm tra đúng:

- Part: `xc7z010clg400-1`.
- Top function: `quantum_simulator`.
- Clock: 10 ns.
- Clock uncertainty: 1 ns.
- Design source: `qsim_hls.cpp`.
- Testbench: `qsim_tb.cpp`.

Không sửa pragma, part, clock hoặc testbench giữa các lần chạy. Nếu thay một trong các yếu tố đó, số liệu không còn là phép so sánh có kiểm soát.

## 2. Chạy thủ công bằng giao diện

Thực hiện lần lượt V1 đến V6:

1. Mở Vitis và tạo HLS Component mới trong một workspace trống.
2. Đặt tên component, ví dụ `qsim8_8q_v1`.
3. Chọn `v1/qsim_hls.cpp` làm Design Source.
4. Chọn `quantum_simulator` làm Top Function.
5. Chọn `v1/qsim_tb.cpp` làm Testbench Source.
6. Chọn part `xc7z010clg400-1`, clock 10 ns, uncertainty 1 ns.
7. Kiểm tra `hls_config.cfg` của đúng phiên bản. V1 dùng `pipeline_loops=64`; V2-V6 dùng `pipeline_loops=0`.
8. Chạy **C Simulation**. Chỉ tiếp tục khi cuối log có `PASS: 18/18`.
9. Chạy **C Synthesis** và lưu Summary, Performance & Resource Estimates, Schedule Viewer.
10. Chạy **C/RTL Co-simulation** với Verilog. Kết quả phải là `Pass`.
11. Không cần Export IP cho phép so sánh tài nguyên này.

Mỗi component phải trỏ tới thư mục phiên bản tương ứng. Không dùng source V1 với config V3.

## 3. Chạy C Synthesis bằng PowerShell

Có thể chạy một bản:

```powershell
if (-not $env:XILINX_VITIS) { throw 'Đặt XILINX_VITIS tới thư mục Vitis 2026.1' }
$vitisCompiler = Join-Path $env:XILINX_VITIS 'bin\v++.bat'
if (-not (Test-Path -LiteralPath $vitisCompiler)) { throw 'Đặt XILINX_VITIS tới thư mục Vitis 2026.1' }
Set-Location .\research\hls_v1_v6\v1
$work = Join-Path (Get-Location) '..\build\v1'
if (Test-Path -LiteralPath $work) { throw 'Chọn work_dir mới chưa tồn tại' }
& $vitisCompiler -c --mode hls `
  --config '.\hls_config.cfg' `
  --work_dir $work
```

Đổi `v1` thành `v2` đến `v6` cho các bản còn lại. Hoặc dùng script:

```powershell
# Trở về thư mục gốc của repository trước khi chạy lệnh sau.
& .\research\hls_v1_v6\scripts\RunSynthesisAll.ps1
```

Script PowerShell chỉ thực hiện HLS compile/C Synthesis. C Simulation và C/RTL Co-simulation nên chạy trong GUI để bạn quan sát rõ kết quả và schedule.

## 4. Thu báo cáo tự động

Sau khi chạy đủ sáu bản:

```powershell
# Chạy từ thư mục gốc của repository.
& .\.venv\Scripts\python.exe .\research\hls_v1_v6\scripts\collect_reports.py
```

Script tìm `hls_compile.rpt` và `hls_cosim.rpt` trong `build/v1` đến `build/v6`, sau đó tạo bảng chung trong `reports`.

Nếu script chưa nhận report, hãy sao chép report của mỗi component vào:

```text
build/v1/.../reports/hls_compile.rpt
build/v2/.../reports/hls_compile.rpt
...
build/v6/.../reports/hls_compile.rpt
```

Khi đối chiếu, dùng báo cáo sinh từ cùng phiên bản Vitis và cùng cấu hình; không ghép số liệu của các lần chạy khác nhau.

## 5. Ảnh và bằng chứng nên lưu

Với mỗi phiên bản, lưu:

- Màn hình C Simulation có `PASS: 18/18`.
- HLS Synthesis Summary.
- Bảng resource BRAM/DSP/FF/LUT.
- Loop latency/II cho `single_gate_loop` và `controlled_gate_loop`.
- C/RTL Co-simulation có trạng thái `Pass`.
- Phiên bản Vitis và thời điểm chạy.

Các report dạng text là bằng chứng chính; ảnh chụp chỉ dùng để minh họa báo cáo.
