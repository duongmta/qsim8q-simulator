# Báo cáo V1-V6

Thư mục này chứa bảng bằng chứng được sinh từ báo cáo Vitis HLS mới.

Sau khi chạy C Synthesis/Cosim cho V1-V6, thực hiện:

```powershell
# Chạy từ thư mục gốc của repository.
& .\.venv\Scripts\python.exe .\research\hls_v1_v6\scripts\collect_reports.py
```

Không chép các số liệu 15 qubit/Zynq-7020 cũ vào bảng chuẩn hóa 8 qubit/Zynq-7010.
