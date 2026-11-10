# Thành phần bên thứ ba

| Thành phần | Vị trí / cách sử dụng | Giấy phép |
|---|---|---|
| Xilinx/AMD `ap_types` | `experiments/cd3_python_core/ap_types/`, dùng khi biên dịch lõi C++ trên máy tính | Apache License 2.0; giữ nguyên thông báo bản quyền trong từng header và `ap_types/LICENSE.TXT` |
| Qiskit, Qiskit Aer, NumPy, PySerial, Pydantic, Matplotlib, pytest và các phụ thuộc Python | Được cài riêng từ `pyproject.toml`; không chép mã của các gói này vào repository | Theo giấy phép của từng dự án upstream |

`LICENSE` ở thư mục gốc áp dụng cho mã QSim8Q do dự án công bố. Nó không thay thế giấy phép hoặc thông báo bản quyền của thành phần bên thứ ba.
