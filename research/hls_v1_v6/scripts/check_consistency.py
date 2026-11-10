from __future__ import annotations

import hashlib
import re
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
VERSIONS = [f"v{i}" for i in range(1, 7)]


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def require(pattern: str, text: str, label: str) -> None:
    if re.search(pattern, text, flags=re.MULTILINE) is None:
        raise AssertionError(f"Thiếu hoặc sai {label}: /{pattern}/")


def main() -> int:
    errors: list[str] = []
    tb_hashes: dict[str, str] = {}

    for version in VERSIONS:
        folder = ROOT / version
        try:
            header = (folder / "qsim_hls.h").read_text(encoding="utf-8-sig")
            source = (folder / "qsim_hls.cpp").read_text(encoding="utf-8-sig")
            config = (folder / "hls_config.cfg").read_text(encoding="utf-8-sig")
            testbench = folder / "qsim_tb.cpp"

            require(r"^part=xc7z010clg400-1$", config, "part")
            require(r"^clock=10ns$", config, "clock")
            require(r"^clock_uncertainty=1ns$", config, "clock uncertainty")
            require(r"^syn\.top=quantum_simulator$", config, "top")
            require(r"^#define MAX_QUBITS 8$", header, "MAX_QUBITS")
            require(r"^#define MAX_INSTRUCTIONS 256$", header, "MAX_INSTRUCTIONS")
            require(r"ap_fixed<32, 2, AP_RND_CONV, AP_SAT>", header, "Q2.30")
            require(r"GATE_H", header, "gate H")
            require(r"GATE_CZ", header, "gate CZ")
            require(r"void quantum_simulator", source, "top implementation")
            tb_hashes[version] = sha256(testbench)
        except (OSError, AssertionError) as exc:
            errors.append(f"{version}: {exc}")

    if len(set(tb_hashes.values())) != 1:
        errors.append("Testbench không giống hệt nhau giữa V1-V6")

    try:
        cfg1 = (ROOT / "v1" / "hls_config.cfg").read_text(encoding="utf-8-sig")
        require(r"^syn\.compile\.pipeline_loops=64$", cfg1, "V1 auto-pipeline")
        for version in VERSIONS[1:]:
            cfg = (ROOT / version / "hls_config.cfg").read_text(encoding="utf-8-sig")
            require(r"^syn\.compile\.pipeline_loops=0$", cfg, f"{version} auto-pipeline off")

        h2 = (ROOT / "v2" / "qsim_hls.h").read_text(encoding="utf-8-sig")
        h3 = (ROOT / "v3" / "qsim_hls.h").read_text(encoding="utf-8-sig")
        require(r"#define QSIM_ENABLE_PIPELINE 0", h2, "V2 pipeline off")
        require(r"#define QSIM_ENABLE_PIPELINE 1", h3, "V3 pipeline on")

        s3 = (ROOT / "v3" / "qsim_hls.cpp").read_text(encoding="utf-8-sig")
        s4 = (ROOT / "v4" / "qsim_hls.cpp").read_text(encoding="utf-8-sig")
        require(r"#pragma HLS PIPELINE II=1", s3, "V3 II=1")
        if "#pragma HLS PIPELINE II=1" in s4:
            raise AssertionError("V4 vẫn còn ép II=1")

        s5 = (ROOT / "v5" / "qsim_hls.cpp").read_text(encoding="utf-8-sig")
        require(r"state_word_t state_a\[NUM_STATES\]", s5, "V5 state_a")
        require(r"state_word_t state_b\[NUM_STATES\]", s5, "V5 state_b")

        s6 = (ROOT / "v6" / "qsim_hls.cpp").read_text(encoding="utf-8-sig")
        require(r"state_word_t local_state\[NUM_STATES\]", s6, "V6 local_state")
        require(r"DEPENDENCE variable=state inter false", s6, "V6 dependence")
        require(r"PIPELINE II=QSIM_V6_TARGET_II", s6, "V6 target II")
    except (OSError, AssertionError) as exc:
        errors.append(str(exc))

    if errors:
        print("CONSISTENCY_CHECK: FAIL")
        for error in errors:
            print(f"- {error}")
        return 1

    print("CONSISTENCY_CHECK: PASS")
    print("- Part: xc7z010clg400-1")
    print("- Clock: 10 ns, uncertainty: 1 ns")
    print("- Scope: 1-8 qubits, 256 amplitudes, 256 instructions")
    print("- Numeric type: Q2.30")
    print("- Shared testbench SHA256:", next(iter(tb_hashes.values())))
    print("- Intended optimization differences V1-V6 are present")
    return 0


if __name__ == "__main__":
    sys.exit(main())

