"""Build and run the standalone QSim8 FP32 CPU profiler.

Qiskit is used only before timing to create the exact transpiled circuits and
golden statevectors. All timed state-vector work is performed by profile_cpu.cpp.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import os
import platform
import shutil
import statistics
import subprocess
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

_LOCAL_BUILD = Path(__file__).resolve().parent / "build"
os.environ.setdefault("MPLCONFIGDIR", str(_LOCAL_BUILD / "matplotlib"))

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from qiskit import QuantumCircuit, transpile
from qiskit.quantum_info import Statevector

from qsim8_backend.benchmark_scaling import DEPTH_GRID, QUBIT_GRID, make_scaling_circuit
from qsim8_backend.qiskit_adapter import compile_quantum_circuit
from qsim8_backend.qiskit_backend import QSim8Backend

for _stream in (sys.stdout, sys.stderr):
    _reconfigure = getattr(_stream, "reconfigure", None)
    if _reconfigure is not None:
        _reconfigure(encoding="utf-8", errors="replace")


ROOT = Path(__file__).resolve().parents[1]
HERE = Path(__file__).resolve().parent
BUILD = HERE / "build"
RESULTS = ROOT / "results" / "cpu_profiling"
SEED_TRANSPILER = 1729
PHASES = ("execute", "kernel_1q", "kernel_2q", "dispatch", "reset", "copy")


def utc_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def percentile(values: list[float], value: float) -> float:
    return float(np.percentile(np.asarray(values, dtype=float), value))


def stats(values: list[float]) -> dict[str, float]:
    median = statistics.median(values)
    mean = statistics.fmean(values)
    deviation = statistics.stdev(values) if len(values) > 1 else 0.0
    mad = statistics.median(abs(value - median) for value in values)
    return {
        "median": median,
        "p95": percentile(values, 95),
        "min": min(values),
        "max": max(values),
        "mean": mean,
        "stdev": deviation,
        "cv_percent": 100.0 * deviation / mean if mean else 0.0,
        "robust_cv_percent": 100.0 * 1.4826 * mad / median if median else 0.0,
    }


def native_gates(compiled) -> list[dict]:
    native = []
    for gate in sorted(compiled.circuit.gates, key=lambda item: (item.layer, item.target)):
        row = gate.model_dump()
        if row["gate"] == "SWAP":
            control, target = row["control"], row["target"]
            native.extend([
                {"gate": "CNOT", "control": control, "target": target, "theta": None},
                {"gate": "CNOT", "control": target, "target": control, "theta": None},
                {"gate": "CNOT", "control": control, "target": target, "theta": None},
            ])
        else:
            native.append(row)
    if len(native) != compiled.summary["native_instructions"]:
        raise RuntimeError("Native instruction expansion disagrees with Backend compiler")
    return native


def compile_case(backend: QSim8Backend, circuit: QuantumCircuit, suite: str,
                 requested_depth: int | None = None) -> dict:
    transpiled = transpile(
        circuit, backend=backend, optimization_level=0,
        seed_transpiler=SEED_TRANSPILER,
    )
    compiled = compile_quantum_circuit(transpiled)
    gates = native_gates(compiled)
    expected = np.asarray(Statevector.from_instruction(transpiled).data, dtype=np.complex128)
    return {
        "id": circuit.name,
        "suite": suite,
        "num_qubits": transpiled.num_qubits,
        "depth": requested_depth if requested_depth is not None else transpiled.depth(),
        "gates": gates,
        "expected": expected,
        "one_q_count": sum(g["gate"] not in {"CNOT", "CZ"} for g in gates),
        "two_q_count": sum(g["gate"] in {"CNOT", "CZ"} for g in gates),
        "qiskit_depth": transpiled.depth(),
    }


def one_q_circuit(num_qubits: int, gate: str, target: int) -> QuantumCircuit:
    qc = QuantumCircuit(num_qubits, name=f"MICRO_{gate}_{num_qubits}Q_q{target}")
    if gate in {"RX", "RY", "RZ"}:
        getattr(qc, gate.lower())(0.731, target)
    else:
        getattr(qc, gate.lower())(target)
    return qc


def two_q_circuit(num_qubits: int, gate: str, control: int,
                  target: int) -> QuantumCircuit:
    qc = QuantumCircuit(
        num_qubits, name=f"MICRO_{gate}_{num_qubits}Q_q{control}_q{target}"
    )
    method = "cx" if gate == "CNOT" else gate.lower()
    getattr(qc, method)(control, target)
    return qc


def build_cases(quick: bool) -> list[dict]:
    backend = QSim8Backend(port="COM14")  # Construction/transpile does not open UART.
    cases = []
    qubits = (1, 4, 8) if quick else QUBIT_GRID
    depths = (1, 10, 20) if quick else DEPTH_GRID
    for num_qubits in qubits:
        for depth in depths:
            cases.append(compile_case(
                backend, make_scaling_circuit(num_qubits, depth),
                "scaling", requested_depth=depth,
            ))

    micro_circuits: dict[str, QuantumCircuit] = {}
    representative_qubits = (1, 4, 8) if quick else QUBIT_GRID
    for num_qubits in representative_qubits:
        for gate in ("H", "RX"):
            qc = one_q_circuit(num_qubits, gate, 0)
            micro_circuits[qc.name] = qc
    for num_qubits in (() if quick else range(2, 9)):
        for gate in ("CNOT", "CZ"):
            qc = two_q_circuit(num_qubits, gate, 0, num_qubits - 1)
            micro_circuits[qc.name] = qc

    # Characterize every supported 1Q gate and near/far 2Q access at 8 qubits.
    if not quick:
        for gate in ("H", "X", "Y", "Z", "S", "T", "RX", "RY", "RZ"):
            for target in (0, 7):
                qc = one_q_circuit(8, gate, target)
                micro_circuits[qc.name] = qc
        for gate in ("CNOT", "CZ", "SWAP"):
            for control, target in ((0, 1), (0, 7)):
                qc = two_q_circuit(8, gate, control, target)
                micro_circuits[qc.name] = qc

    for qc in micro_circuits.values():
        cases.append(compile_case(backend, qc, "micro"))
    return cases


def write_suite(path: Path, cases: list[dict]) -> None:
    with path.open("w", encoding="utf-8", newline="\n") as stream:
        stream.write("# QSim8 CPU profiling suite v1\n")
        for case in cases:
            stream.write(
                f"CASE\t{case['id']}\t{case['suite']}\t{case['num_qubits']}\t"
                f"{case['depth']}\t{len(case['gates'])}\n"
            )
            for gate in case["gates"]:
                control = -1 if gate.get("control") is None else gate["control"]
                theta = 0.0 if gate.get("theta") is None else gate["theta"]
                stream.write(
                    f"GATE\t{gate['gate']}\t{gate['target']}\t{control}\t"
                    f"{float(theta):.17g}\n"
                )
            for value in case["expected"]:
                stream.write(f"REF\t{value.real:.17g}\t{value.imag:.17g}\n")
            stream.write("END\n")


def find_compiler(explicit: str | None) -> str:
    candidates = [explicit, os.environ.get("CXX"), shutil.which("g++"),
                  shutil.which("clang++")]
    for candidate in candidates:
        if candidate and Path(candidate).is_file():
            return str(Path(candidate).resolve())
    raise RuntimeError(
        "Không tìm thấy g++/clang++. Máy hiện tại có thể dùng "
        r"C:\msys64\ucrt64\bin\g++.exe hoặc truyền --compiler PATH."
    )


def build_profiler(compiler: str, executable: Path) -> tuple[list[str], str]:
    executable.parent.mkdir(parents=True, exist_ok=True)
    command = [
        compiler, "-std=c++17", "-O3", "-DNDEBUG", "-Wall", "-Wextra",
        str(HERE / "qsim_cpu.cpp"), str(HERE / "profile_cpu.cpp"),
        "-o", str(executable),
    ]
    subprocess.run(command, cwd=ROOT, check=True)
    version = subprocess.run(
        [compiler, "--version"], text=True, capture_output=True, check=True
    ).stdout.splitlines()[0]
    return command, version


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as stream:
        return list(csv.DictReader(stream))


def build_summary(raw_path: Path, validation_path: Path, cases: list[dict]) -> list[dict]:
    timings: dict[tuple[str, str], list[float]] = defaultdict(list)
    for row in read_csv(raw_path):
        timings[(row["case_id"], row["phase"])].append(float(row["ns_per_run"]))
    validation = {row["case_id"]: row for row in read_csv(validation_path)}

    rows = []
    for case in cases:
        phase_stats = {
            phase: stats(timings[(case["id"], phase)])
            if timings[(case["id"], phase)] else None
            for phase in PHASES
        }
        one_ns = phase_stats["kernel_1q"]["median"] if phase_stats["kernel_1q"] else 0.0
        two_ns = phase_stats["kernel_2q"]["median"] if phase_stats["kernel_2q"] else 0.0
        dispatch_ns = phase_stats["dispatch"]["median"]
        phase_sum = one_ns + two_ns + dispatch_ns
        pairs = len(case["gates"]) * (1 << (case["num_qubits"] - 1))
        iterations = (
            case["one_q_count"] * (1 << (case["num_qubits"] - 1))
            + case["two_q_count"] * (1 << case["num_qubits"])
        )
        execute_ns = phase_stats["execute"]["median"]
        check = validation[case["id"]]
        row = {
            "case_id": case["id"], "suite": case["suite"],
            "num_qubits": case["num_qubits"], "depth": case["depth"],
            "native_instructions": len(case["gates"]),
            "one_q_count": case["one_q_count"], "two_q_count": case["two_q_count"],
            "logical_amplitude_pairs": pairs, "cpu_loop_iterations": iterations,
            "execute_median_us": execute_ns / 1000.0,
            "execute_p95_us": phase_stats["execute"]["p95"] / 1000.0,
            "execute_cv_percent": phase_stats["execute"]["cv_percent"],
            "execute_robust_cv_percent": phase_stats["execute"]["robust_cv_percent"],
            "kernel_1q_median_us": one_ns / 1000.0,
            "kernel_2q_median_us": two_ns / 1000.0,
            "dispatch_median_us": dispatch_ns / 1000.0,
            "reset_median_us": phase_stats["reset"]["median"] / 1000.0,
            "copy_median_us": phase_stats["copy"]["median"] / 1000.0,
            "estimated_1q_share_percent": 100.0 * one_ns / phase_sum if phase_sum else 0.0,
            "estimated_2q_share_percent": 100.0 * two_ns / phase_sum if phase_sum else 0.0,
            "estimated_dispatch_share_percent": 100.0 * dispatch_ns / phase_sum if phase_sum else 0.0,
            "million_loop_iterations_per_s": iterations / execute_ns * 1000.0 if execute_ns else 0.0,
            "max_error_vs_qiskit": float(check["max_error"]),
            "fidelity_vs_qiskit": float(check["fidelity"]),
            "norm_error": float(check["norm_error"]),
            "validation": check["status"],
        }
        rows.append(row)
    return rows


def write_summary(path: Path, rows: list[dict]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def save_figure(fig, folder: Path, stem: str) -> None:
    fig.tight_layout()
    for suffix in ("png", "svg"):
        fig.savefig(folder / f"{stem}.{suffix}", dpi=180, bbox_inches="tight")
    plt.close(fig)


def create_charts(rows: list[dict], folder: Path) -> list[str]:
    scaling = [row for row in rows if row["suite"] == "scaling"]
    names = []

    fig, ax = plt.subplots(figsize=(8.6, 5.2))
    depths = sorted({row["depth"] for row in scaling})
    for depth in depths:
        selected = sorted((row for row in scaling if row["depth"] == depth),
                          key=lambda row: row["num_qubits"])
        ax.plot([row["num_qubits"] for row in selected],
                [row["execute_median_us"] for row in selected], marker="o",
                label=f"Depth {depth}")
    ax.set(xlabel="Số qubit", ylabel="CPU execute median (µs)",
           title="Thời gian lõi CPU theo số qubit")
    ax.grid(alpha=0.25); ax.legend(ncol=2)
    save_figure(fig, folder, "01_cpu_time_vs_qubits"); names.append("01_cpu_time_vs_qubits.png")

    fig, ax = plt.subplots(figsize=(8.6, 5.2))
    for qubits in sorted({row["num_qubits"] for row in scaling}):
        selected = sorted((row for row in scaling if row["num_qubits"] == qubits),
                          key=lambda row: row["depth"])
        ax.plot([row["depth"] for row in selected],
                [row["execute_median_us"] for row in selected], marker="o",
                label=f"{qubits}Q")
    ax.set(xlabel="Độ sâu logic", ylabel="CPU execute median (µs)",
           title="Thời gian lõi CPU theo độ sâu")
    ax.grid(alpha=0.25); ax.legend(ncol=4)
    save_figure(fig, folder, "02_cpu_time_vs_depth"); names.append("02_cpu_time_vs_depth.png")

    selected = sorted(scaling, key=lambda row: (row["num_qubits"], row["depth"]))
    labels = [f"{r['num_qubits']}Q/{r['depth']}L" for r in selected]
    one = [r["estimated_1q_share_percent"] for r in selected]
    two = [r["estimated_2q_share_percent"] for r in selected]
    dispatch = [r["estimated_dispatch_share_percent"] for r in selected]
    fig, ax = plt.subplots(figsize=(12.5, 5.5))
    x = np.arange(len(selected))
    ax.bar(x, one, label="Kernel 1Q")
    ax.bar(x, two, bottom=one, label="Kernel 2Q")
    ax.bar(x, dispatch, bottom=np.asarray(one) + np.asarray(two), label="Dispatch")
    ax.set_xticks(x, labels, rotation=70, ha="right", fontsize=7)
    ax.set(ylabel="Tỷ lệ ước lượng (%)", title="Phân bố hotspot theo pha")
    ax.legend(ncol=3); ax.grid(axis="y", alpha=0.2)
    save_figure(fig, folder, "03_hotspot_share"); names.append("03_hotspot_share.png")

    micro8 = [row for row in rows if row["suite"] == "micro" and row["num_qubits"] == 8]
    micro8 = sorted(micro8, key=lambda row: row["case_id"])
    if micro8:
        fig, ax = plt.subplots(figsize=(12.5, 5.8))
        ns_per_pair = [r["execute_median_us"] * 1000 / r["logical_amplitude_pairs"] for r in micro8]
        ax.bar(np.arange(len(micro8)), ns_per_pair)
        ax.set_xticks(np.arange(len(micro8)), [r["case_id"].replace("MICRO_", "") for r in micro8],
                      rotation=70, ha="right", fontsize=7)
        ax.set(ylabel="ns / cặp amplitude logic", title="Microbenchmark các cổng ở 8 qubit")
        ax.grid(axis="y", alpha=0.2)
        save_figure(fig, folder, "04_gate_cost_8q"); names.append("04_gate_cost_8q.png")

    fig, ax = plt.subplots(figsize=(8.6, 5.2))
    ax.scatter([r["cpu_loop_iterations"] for r in scaling],
               [r["execute_median_us"] for r in scaling],
               c=[r["num_qubits"] for r in scaling], cmap="viridis")
    ax.set(xlabel="Số vòng lặp kernel theo thuật toán",
           ylabel="CPU execute median (µs)",
           title="Quan hệ khối lượng công việc và thời gian CPU")
    ax.grid(alpha=0.25)
    save_figure(fig, folder, "05_time_vs_work"); names.append("05_time_vs_work.png")
    return names


def md_table(rows: list[dict], columns: list[tuple[str, str, str]]) -> str:
    header = "| " + " | ".join(label for _, label, _ in columns) + " |"
    align = "| " + " | ".join("---:" if fmt != "s" else "---" for _, _, fmt in columns) + " |"
    lines = [header, align]
    for row in rows:
        cells = []
        for key, _, fmt in columns:
            value = row[key]
            cells.append(str(value) if fmt == "s" else format(value, fmt))
        lines.append("| " + " | ".join(cells) + " |")
    return "\n".join(lines)


def write_report(path: Path, rows: list[dict], manifest: dict, chart_names: list[str]) -> None:
    scaling = [row for row in rows if row["suite"] == "scaling"]
    micro = [row for row in rows if row["suite"] == "micro"]
    validations = sum(row["validation"] == "PASS" for row in rows)
    work = np.asarray([row["cpu_loop_iterations"] for row in scaling], dtype=float)
    timing = np.asarray([row["execute_median_us"] for row in scaling], dtype=float)
    correlation = float(np.corrcoef(work, timing)[0, 1]) if len(work) > 1 else math.nan
    hotspot_case = max(scaling, key=lambda row: (row["num_qubits"], row["depth"]))
    shares = {
        "kernel 1Q": hotspot_case["estimated_1q_share_percent"],
        "kernel 2Q": hotspot_case["estimated_2q_share_percent"],
        "dispatch": hotspot_case["estimated_dispatch_share_percent"],
    }
    hotspot = max(shares, key=shares.get)
    max_cv_row = max(scaling, key=lambda row: row["execute_cv_percent"])
    max_robust_cv_row = max(scaling, key=lambda row: row["execute_robust_cv_percent"])
    unstable_count = sum(row["execute_robust_cv_percent"] > 10.0 for row in scaling)

    columns = [
        ("case_id", "Ca", "s"), ("num_qubits", "Qubit", "d"),
        ("depth", "Depth", "d"), ("native_instructions", "Lệnh", "d"),
        ("execute_median_us", "Median µs", ".4f"),
        ("execute_p95_us", "P95 µs", ".4f"),
        ("execute_robust_cv_percent", "Robust CV %", ".2f"),
        ("million_loop_iterations_per_s", "Miter/s", ".2f"),
        ("validation", "Qiskit", "s"),
    ]
    micro_columns = [
        ("case_id", "Ca vi mô", "s"), ("native_instructions", "Lệnh", "d"),
        ("execute_median_us", "Median µs", ".4f"),
        ("execute_robust_cv_percent", "Robust CV %", ".2f"),
        ("validation", "Qiskit", "s"),
    ]
    mode_note = (
        "Đây là lần chạy nhanh để kiểm tra công cụ; chưa dùng các số liệu này làm kết quả chính thức."
        if manifest["configuration"]["quick"] else
        "Đây là bộ đo đầy đủ 1–8 qubit × depth 1/5/10/15/20 và microbenchmark."
    )
    text = f"""# Báo cáo profiling CPU QSim8Q

## Phạm vi và phương pháp

{mode_note}

- Lõi được đo: state-vector C++ FP32, một luồng, biên dịch Release `-O3`.
- Qiskit chỉ sinh mạch đã transpile và state-vector chuẩn trước khi đo.
- UART, web, ghi CSV và Qiskit/Aer không nằm trong vùng thời gian.
- Mỗi phép đo dùng batch tự hiệu chỉnh tối thiểu {manifest['configuration']['min_batch_ms']} ms, {manifest['configuration']['samples']} mẫu và {manifest['configuration']['warmup']} warm-up.
- Tiến trình được ghim vào CPU logic {manifest['configuration']['affinity_cpu']} để tránh di chuyển giữa lõi P/E.
- `kernel_1q`, `kernel_2q` và `dispatch` được đo tách biệt; tỷ lệ hotspot là tỷ lệ ước lượng từ ba phép đo này.
- `reset` và `copy` là chi phí biên được báo riêng, không cộng vào `execute`.

## Môi trường

- CPU: {manifest['environment']['cpu']}
- Hệ điều hành: {manifest['environment']['platform']}
- Compiler: {manifest['compiler']['version']}
- Số CPU logic: {manifest['environment']['logical_cpu_count']}
- UTC: {manifest['created_utc']}

## Kiểm tra tính đúng

- Kết quả FP32 đạt so với state-vector Qiskit: **{validations}/{len(rows)}** ca.
- Ngưỡng kiểm tra: `max_error ≤ 1e-5`, `fidelity ≥ 1 - 1e-7`, `norm_error ≤ 1e-5`.
- So sánh đã loại global phase trước khi tính sai số cực đại.

## Chất lượng số đo

- Robust CV lớn nhất trong 40 ca scaling: **{max_robust_cv_row['execute_robust_cv_percent']:.2f}%** tại `{max_robust_cv_row['case_id']}`.
- Số ca scaling có robust CV lớn hơn 10%: **{unstable_count}/40**.
- CV thường lớn nhất là **{max_cv_row['execute_cv_percent']:.2f}%** tại `{max_cv_row['case_id']}`; giá trị này nhạy với ngắt hệ điều hành và vẫn được giữ trong CSV.
- Báo cáo dùng median làm giá trị trung tâm, robust CV đánh giá độ ổn định và p95 thể hiện nhiễu lập lịch.

## Benchmark mở rộng

{md_table(scaling, columns)}

## Hotspot

Ở ca `{hotspot_case['case_id']}`, tỷ lệ ước lượng là:

| Pha | Tỷ lệ |
|---|---:|
| Kernel 1Q | {hotspot_case['estimated_1q_share_percent']:.2f}% |
| Kernel 2Q | {hotspot_case['estimated_2q_share_percent']:.2f}% |
| Dispatch | {hotspot_case['estimated_dispatch_share_percent']:.2f}% |

Pha lớn nhất trong ca này là **{hotspot}**. Hệ số tương quan Pearson giữa số vòng lặp kernel theo thuật toán và thời gian `execute` của ma trận scaling là **{correlation:.6f}**. Kết luận này chỉ áp dụng cho cấu hình CPU và phạm vi 1–8 qubit của lần đo.

Các vùng mã tương ứng là `apply_single_qubit_gate`, `apply_two_qubit_gate` và
`execute_circuit` trong `cpu_profile/qsim_cpu.cpp`. Mỗi cổng 1Q duyệt
`2^(n-1)` cặp amplitude; mã CPU 2Q hiện duyệt `2^n` chỉ số và cập nhật tập con
thỏa bit control/target. Đây là các vòng lặp cần đối chiếu với pipeline và tổ
chức BRAM của HLS V1–V6.

## Microbenchmark

{md_table(micro, micro_columns)}

## Biểu đồ

"""
    for name in chart_names:
        text += f"\n![{name}](charts/{name})\n"
    text += """

## Diễn giải cho thuyết minh

Số vòng lặp cập nhật state-vector tăng theo số lệnh và theo số amplitude. Số liệu `kernel_1q`, `kernel_2q` và `dispatch` cho biết phần nào chiếm thời gian thay vì suy luận từ mã nguồn. Đây là căn cứ nối công việc profiling CPU với các thử nghiệm PIPELINE, BRAM, dữ liệu đóng gói và Q2.30 trong HLS V1–V6.

State-vector 8 qubit FP32 chỉ có 256 số phức, khoảng 2 KiB, thường nằm trong cache L1. Kết quả không được diễn giải thành bằng chứng nghẽn DRAM ở quy mô lớn. Trên FPGA, giới hạn truy cập BRAM/II là vấn đề kiến trúc riêng được chứng minh bằng báo cáo HLS.

## Tệp dữ liệu

- `cpu_profile_raw.csv`: từng mẫu và batch repetitions.
- `cpu_profile_summary.csv`: median, p95, CV, phân bố pha và độ chính xác.
- `validation.csv`: đối chiếu FP32 với Qiskit.
- `manifest.json`: môi trường, cấu hình, lệnh biên dịch và hash mã nguồn.
- `suite.tsv`: mạch native và state-vector Qiskit đã dùng.
"""
    path.write_text(text, encoding="utf-8")


def cpu_name() -> str:
    if sys.platform == "win32":
        commands = [
            "[string](Get-ItemProperty -LiteralPath "
            "'Registry::HKEY_LOCAL_MACHINE\\HARDWARE\\DESCRIPTION\\System\\CentralProcessor\\0' "
            "-Name ProcessorNameString).ProcessorNameString",
            "(Get-CimInstance Win32_Processor | Select-Object -First 1 -ExpandProperty Name)",
        ]
        for command in commands:
            try:
                result = subprocess.run(
                    ["powershell", "-NoProfile", "-Command", command],
                    text=True, capture_output=True, timeout=10, check=True,
                )
                if result.stdout.strip():
                    return result.stdout.strip()
            except (OSError, subprocess.SubprocessError):
                pass
    return platform.processor() or platform.machine() or "unknown"


def copy_latest(run_folder: Path) -> None:
    RESULTS.mkdir(parents=True, exist_ok=True)
    for source_name, latest_name in (
        ("CPU_PROFILING_REPORT.md", "latest_report.md"),
        ("cpu_profile_summary.csv", "latest_summary.csv"),
        ("manifest.json", "latest_manifest.json"),
    ):
        shutil.copy2(run_folder / source_name, RESULTS / latest_name)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="QSim8 standalone FP32 CPU profiler")
    parser.add_argument("--quick", action="store_true",
                        help="Smoke run: 9 scaling cases and a small micro subset")
    parser.add_argument("--samples", type=int, default=None)
    parser.add_argument("--warmup", type=int, default=None)
    parser.add_argument("--min-batch-ms", type=float, default=None)
    parser.add_argument("--compiler")
    parser.add_argument("--affinity-cpu", type=int, default=4,
                        help="Logical CPU used by the C++ process; -1 disables pinning")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    samples = args.samples if args.samples is not None else (5 if args.quick else 20)
    warmup = args.warmup if args.warmup is not None else (1 if args.quick else 3)
    min_batch_ms = args.min_batch_ms if args.min_batch_ms is not None else (2.0 if args.quick else 10.0)
    if samples < 1 or warmup < 0 or min_batch_ms <= 0:
        raise SystemExit("samples >= 1, warmup >= 0 và min-batch-ms > 0")

    run_folder = RESULTS / f"{utc_stamp()}_{'quick' if args.quick else 'full'}"
    charts = run_folder / "charts"
    charts.mkdir(parents=True)
    suite_path = run_folder / "suite.tsv"
    raw_path = run_folder / "cpu_profile_raw.csv"
    validation_path = run_folder / "validation.csv"
    summary_path = run_folder / "cpu_profile_summary.csv"
    executable = BUILD / "qsim8_cpu_profile.exe"

    print("Tạo mạch Qiskit và state-vector tham chiếu (không mở UART)...")
    cases = build_cases(args.quick)
    write_suite(suite_path, cases)
    compiler = find_compiler(args.compiler)
    print(f"Biên dịch profiler bằng {compiler}...")
    build_command, compiler_version = build_profiler(compiler, executable)

    command = [
        str(executable), "--input", str(suite_path),
        "--raw-output", str(raw_path),
        "--validation-output", str(validation_path),
        "--samples", str(samples), "--warmup", str(warmup),
        "--min-batch-ms", str(min_batch_ms),
        "--affinity-cpu", str(args.affinity_cpu),
    ]
    print("Chạy lõi C++ FP32...")
    subprocess.run(command, cwd=ROOT, check=True)

    rows = build_summary(raw_path, validation_path, cases)
    write_summary(summary_path, rows)
    chart_names = create_charts(rows, charts)
    manifest = {
        "schema_version": 1,
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "scope": "QSim8 1..8 qubits, FP32 CPU state-vector, single process/thread",
        "configuration": {
            "quick": args.quick, "samples": samples, "warmup": warmup,
            "min_batch_ms": min_batch_ms, "seed_transpiler": SEED_TRANSPILER,
            "case_count": len(cases), "affinity_cpu": args.affinity_cpu,
        },
        "environment": {
            "cpu": cpu_name(), "platform": platform.platform(),
            "python": sys.version, "logical_cpu_count": os.cpu_count(),
        },
        "compiler": {"path": compiler, "version": compiler_version,
                     "command": build_command},
        "execution_command": command,
        "measurement_boundary": {
            "included": "C++ FP32 state initialization/copy/dispatch/1Q/2Q/execute as separate phases",
            "excluded": "Qiskit, transpile, reference statevector, Python, UART, web, file output",
        },
        "validation_policy": {
            "reference": "Qiskit Statevector.from_instruction(transpiled circuit)",
            "global_phase_alignment": True,
            "max_error_limit": 1e-5, "fidelity_min": 1.0 - 1e-7,
            "norm_error_limit": 1e-5,
        },
        "sources": [
            {"path": str(path.relative_to(ROOT)), "sha256": sha256(path)}
            for path in (HERE / "qsim_cpu.hpp", HERE / "qsim_cpu.cpp",
                         HERE / "profile_cpu.cpp", HERE / "run_cpu_profile.py",
                         ROOT / "qsim8_backend" / "benchmark_scaling.py",
                         ROOT / "qsim8_backend" / "qiskit_adapter.py")
        ],
    }
    (run_folder / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    report_path = run_folder / "CPU_PROFILING_REPORT.md"
    write_report(report_path, rows, manifest, chart_names)
    copy_latest(run_folder)

    passed = sum(row["validation"] == "PASS" for row in rows)
    print(f"\nĐối chiếu Qiskit: {passed}/{len(rows)} PASS")
    print(f"Báo cáo: {report_path}")
    print(f"Bản mới nhất: {RESULTS / 'latest_report.md'}")
    if passed != len(rows):
        print("CPU_PROFILE_RESULT: FAIL (xem validation.csv)")
        return 1
    print("CPU_PROFILE_RESULT: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
