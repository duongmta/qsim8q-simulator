# V5 - packed ping-pong

Phần thực và phần ảo được pack trong word 64-bit. Hai state buffer `state_a/state_b` tách đường đọc và ghi, thuận lợi cho pipeline nhưng dự kiến tăng BRAM.

