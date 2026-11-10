# Diễn giải quá trình tối ưu V1-V6

## 1. Nguyên tắc thí nghiệm

Mục tiêu của phép so sánh là trả lời câu hỏi: khi thuật toán, độ chính xác, khối lượng dữ liệu và FPGA không đổi, một chỉ thị HLS hoặc cách tổ chức bộ nhớ ảnh hưởng thế nào đến latency, interval và tài nguyên?

Các đại lượng phải lấy từ cùng phiên bản Vitis HLS 2026.1:

- BRAM18K, DSP, FF, LUT và tỷ lệ sử dụng.
- Estimated clock và timing slack so với clock 10 ns.
- Latency và initiation interval của `single_gate_loop` và `controlled_gate_loop`.
- Kết quả C Simulation và C/RTL Co-simulation.
- Emax, fidelity và normalization error của cùng 18 ca kiểm thử.

## 2. V1 - thiết kế khởi đầu với tối ưu tự động

V1 giữ hai mảng Q2.30 riêng `local_real` và `local_imag`. Mỗi amplitude phức cần truy cập hai mảng. Mã không đặt pipeline thủ công; cấu hình đặt rõ `syn.compile.pipeline_loops=64` để tái hiện cơ chế tự động của Vitis thay vì phụ thuộc giá trị mặc định của từng phiên bản công cụ.

V1 cho biết kết quả mà người thiết kế nhận được trước khi kiểm soát chỉ thị. Nó chưa phải baseline sạch vì công cụ vẫn có thể tự pipeline các vòng lặp nhỏ.

## 3. V2 - baseline kiểm soát

V2 giữ nguyên mã nguồn V1 nhưng đặt `syn.compile.pipeline_loops=0`. Không còn pipeline tự động và `QSIM_ENABLE_PIPELINE=0`, nên đây là baseline chính thức để tính mức thay đổi tài nguyên hoặc latency của V3-V6.

So sánh V1 với V2 cho thấy tác động riêng của auto-pipeline. So sánh V2 với các bản sau cho thấy tác động của chỉ thị và kiến trúc do người thiết kế chủ động thêm vào.

## 4. V3 - pipeline thủ công II=1

V3 bật `QSIM_ENABLE_PIPELINE=1`. Các vòng lặp đọc/ghi trạng thái và vòng lặp cổng được đặt `PIPELINE II=1`.

Mục tiêu là nhận một cặp amplitude mới mỗi chu kỳ. Với hai mảng real/imag và số cổng BRAM hữu hạn, yêu cầu này có thể khiến HLS nhân bản toán tử, tăng tài nguyên hoặc báo không đạt II/timing. V3 là thí nghiệm thông lượng quyết liệt, không mặc nhiên là kiến trúc tốt nhất.

## 5. V4 - pipeline với II do công cụ lựa chọn

V4 bỏ tham số `II=1`, giữ `PIPELINE`. Vitis được phép chọn II có thể lập lịch dựa trên latency phép nhân Q2.30 và số cổng bộ nhớ.

Nếu V4 giảm timing violation hoặc tài nguyên so với V3 nhưng latency tăng, đó là bằng chứng về đánh đổi giữa thông lượng và khả năng đóng timing.

## 6. V5 - hai bộ đệm packed ping-pong

V5 thay hai mảng real/imag bằng hai mảng word phức 64-bit: `state_a` và `state_b`. Mỗi cổng đọc từ một buffer và ghi sang buffer còn lại, rồi đổi vai trò hai buffer.

Ưu điểm dự kiến:

- Loại xung đột đọc-sau-ghi trên cùng state RAM.
- Một lần truy cập mang cả phần thực và phần ảo.
- Thuận lợi cho pipeline có II thấp.

Chi phí dự kiến là BRAM tăng vì phải giữ hai bản đầy đủ của statevector. Kết quả HLS phải xác nhận mức tăng thực tế; không sử dụng con số của bản 15 qubit/Zynq-7020 cũ.

## 7. V6 - một bộ đệm packed in-place

V6 chỉ giữ một `local_state` 64-bit true-dual-port BRAM. Mỗi iteration xử lý một cặp chỉ số không giao nhau với iteration khác. Chỉ thị `DEPENDENCE inter false` mô tả tính độc lập đó cho HLS.

Một iteration cổng một qubit cần hai lần đọc và hai lần ghi trên cùng RAM. Với hai cổng RAM, V6 chủ động đặt II=2. Mục tiêu là giảm BRAM so với V5 trong khi vẫn giữ pipeline có lịch rõ ràng.

V6 được chọn nếu số liệu chứng minh nó tạo cân bằng phù hợp cho Zynq-7010: đủ tài nguyên, đạt timing ở tần số sử dụng và latency chấp nhận được. Không kết luận V6 tốt nhất trước khi có báo cáo mới.

## 8. Quan hệ với lõi QSim8Q cuối cùng

V6 trong bộ này là phiên bản nghiên cứu kiến trúc. Lõi `hls/qsim8.cpp` tại root kế thừa state RAM packed in-place, true-dual-port, pipeline II=2 và dependence directive. Lõi triển khai còn bổ sung kiểm tra gói lệnh, mã trạng thái trả về, local instruction BRAM và tham số AXI phục vụ firmware.

Vì vậy báo cáo nên trình bày hai tầng bằng chứng:

1. V1-V6 chuẩn hóa: chứng minh quá trình lựa chọn kiến trúc.
2. QSim8Q cuối: chứng minh kiến trúc đã chọn được tích hợp và chạy trên bo thật.

## 9. Bảng kết quả cần điền bằng report mới

| Bản | C Sim | RTL Cosim | Slack (ns) | BRAM18K | DSP | FF | LUT | II 1Q | II 2Q | Nhận xét |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|---|
| V1 | Chưa chạy | Chưa chạy | - | - | - | - | - | - | - | Auto-pipeline |
| V2 | Chưa chạy | Chưa chạy | - | - | - | - | - | - | - | Baseline |
| V3 | Chưa chạy | Chưa chạy | - | - | - | - | - | - | - | Ép II=1 |
| V4 | Chưa chạy | Chưa chạy | - | - | - | - | - | - | - | HLS chọn II |
| V5 | Chưa chạy | Chưa chạy | - | - | - | - | - | - | - | Ping-pong |
| V6 | Chưa chạy | Chưa chạy | - | - | - | - | - | - | - | In-place II=2 |

Chạy `scripts/collect_reports.py` bằng Python 3.10 trở lên để tạo bảng có số liệu thật sau khi sáu workspace đã được tổng hợp.
