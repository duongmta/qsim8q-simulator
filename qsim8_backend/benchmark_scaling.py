"""Benchmark QSim8Q theo so qubit va do sau; mac dinh khong mo UART.

Vi du (chay tai thu muc goc project):
  python -m qsim8_backend.benchmark_scaling --reference-only --repeats 1 --warmup 0
  python -m qsim8_backend.benchmark_scaling --hardware --port COM14 --repeats 20 --warmup 2

Day la benchmark mo rong 8 x 5, tach khoi bo 15 ca nghiem thu bat buoc.
"""
import argparse
import csv
import hashlib
import importlib.metadata
import json
import os
import platform
import shutil
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
from qiskit import QuantumCircuit, qasm3, transpile
from qiskit.quantum_info import Statevector

from .circuit import MAX_INSTRUCTIONS, MAX_LAYERS, MAX_QUBITS, compare


ROOT = Path(__file__).resolve().parents[1]
QUBIT_GRID = tuple(range(1, MAX_QUBITS + 1))
DEPTH_GRID = (1, 5, 10, 15, 20)
SEED_TRANSPILER = 1729
GENERATOR_VERSION = "mixed-v1"


def _utc():
    return datetime.now(timezone.utc).isoformat()


def _sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _json_default(value):
    if isinstance(value, np.ndarray):
        return value.tolist()
    if isinstance(value, np.generic):
        return value.item()
    if isinstance(value, Path):
        return str(value)
    raise TypeError(f"Cannot serialize {type(value).__name__}")


def _state_pairs(state):
    return [[float(value.real), float(value.imag)] for value in state]


def _versions():
    packages = {}
    for name in ("qiskit", "qiskit-aer", "numpy", "pyserial", "pydantic"):
        try:
            packages[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            packages[name] = None
    return {
        "python": sys.version,
        "platform": platform.platform(),
        "machine": platform.machine(),
        "processor": platform.processor() or None,
        "logical_cpu_count": os.cpu_count(),
        "packages": packages,
    }


def _provenance():
    names = [
        "qsim8_backend/benchmark_scaling.py",
        "qsim8_backend/qiskit_backend.py",
        "qsim8_backend/qiskit_adapter.py",
        "qsim8_backend/circuit.py",
        "qsim8_backend/protocol.py",
        "qsim8_backend/transport.py",
        "hls/qsim8.cpp",
        "hls/qsim8.hpp",
        "hls/hls_config.cfg",
        "firmware/main.c",
        "firmware/protocol.h",
        "build/hls_gui/qsim8/qsim8/hls/syn/report/qsim8_csynth.rpt",
        "build/hls_gui/qsim8/qsim8/hls/sim/report/qsim8_cosim.rpt",
        "build/qsim8_zybo.xsa",
        "build/vivado/qsim8_zybo.runs/impl_1/system_wrapper.bit",
        "build/vivado/qsim8_zybo.runs/impl_1/system_wrapper_utilization_placed.rpt",
        "build/vivado/qsim8_zybo.runs/impl_1/system_wrapper_timing_summary_routed.rpt",
        "build/vitis/qsim8_app/build/qsim8_app.elf",
    ]
    return {
        "project_root": str(ROOT),
        "files": [
            {
                "path": name,
                "exists": (ROOT / name).is_file(),
                "sha256": _sha256(ROOT / name) if (ROOT / name).is_file() else None,
            }
            for name in names
        ],
        "artifact_hash_scope": (
            "Hash chi xac dinh file tren PC; log nap bo can duoc luu rieng de lien he "
            "bitstream/ELF voi lan benchmark phan cung."
        ),
    }


def _backend_factory(port=None):
    from .qiskit_backend import QSim8Backend

    return QSim8Backend(port=port or "COM14")


def _make_reference(engine):
    if engine == "statevector":
        def evaluate(circuit):
            start = time.perf_counter()
            state = np.asarray(
                Statevector.from_instruction(circuit).data, dtype=np.complex128
            )
            return state, (time.perf_counter() - start) * 1000

        return evaluate

    try:
        from qiskit_aer import AerSimulator
    except ImportError as exc:
        raise RuntimeError(
            "Can qiskit-aer de dung tham chieu Aer; cai requirements.txt hoac "
            "chon --reference statevector de chan doan."
        ) from exc

    simulator = AerSimulator(
        method="statevector", precision="double", max_parallel_threads=1
    )

    def evaluate(circuit):
        saved = circuit.copy()
        saved.save_statevector()
        start = time.perf_counter()
        state = np.asarray(
            simulator.run(saved).result().get_statevector(saved),
            dtype=np.complex128,
        )
        return state, (time.perf_counter() - start) * 1000

    return evaluate


def _apply_pair_layer(circuit, gate, start, idle_gate):
    """Dat cac cong hai qubit roi lap day qubit le de depth khong bi co lai."""
    used = set()
    for first in range(start, circuit.num_qubits - 1, 2):
        second = first + 1
        getattr(circuit, gate)(first, second)
        used.update((first, second))
    for qubit in range(circuit.num_qubits):
        if qubit not in used:
            getattr(circuit, idle_gate)(qubit)


def make_scaling_circuit(num_qubits, target_depth):
    """Tao mach hon hop deterministic co dependency depth dung bang yeu cau."""
    if not 1 <= num_qubits <= MAX_QUBITS:
        raise ValueError(f"num_qubits phai nam trong 1..{MAX_QUBITS}")
    if not 1 <= target_depth <= MAX_LAYERS:
        raise ValueError(f"target_depth phai nam trong 1..{MAX_LAYERS}")

    circuit = QuantumCircuit(
        num_qubits, name=f"MIXED_{num_qubits}Q_{target_depth}L"
    )
    for layer in range(target_depth):
        mode = layer % 5
        if mode == 0:
            for qubit in range(num_qubits):
                circuit.h(qubit)
        elif mode == 1:
            for qubit in range(num_qubits):
                circuit.ry(0.17 * (qubit + 1) + 0.013 * (layer + 1), qubit)
        elif mode == 2:
            _apply_pair_layer(circuit, "cx", start=0, idle_gate="t")
        elif mode == 3:
            for qubit in range(num_qubits):
                circuit.rz(-0.11 * (qubit + 1) + 0.007 * (layer + 1), qubit)
        else:
            # Dich cap mot vi tri de tao lien ket khac lop CNOT. Voi 2 qubit,
            # dung cap duy nhat; voi 1 qubit, idle gate van tao mot lop hop le.
            start = 1 if num_qubits >= 3 else 0
            _apply_pair_layer(circuit, "cz", start=start, idle_gate="s")

    actual_depth = circuit.depth()
    if actual_depth != target_depth:
        raise RuntimeError(
            f"Loi bo sinh: {circuit.name} co depth={actual_depth}, "
            f"yeu cau {target_depth}."
        )
    circuit.metadata = {
        "suite": "scaling",
        "generator": GENERATOR_VERSION,
        "target_depth": target_depth,
    }
    return circuit


def scaling_circuits(qubits=QUBIT_GRID, depths=DEPTH_GRID):
    return [
        make_scaling_circuit(num_qubits, target_depth)
        for num_qubits in qubits
        for target_depth in depths
    ]


def _stats(values):
    if not values:
        return None
    return {
        "count": len(values),
        "median": float(np.median(values)),
        "p95": float(np.percentile(values, 95)),
        "min": float(min(values)),
        "max": float(max(values)),
    }


def _timing_summary(row):
    measured = row.get("measured", [])
    summary = {
        "reference_original_ms": _stats(
            [record["reference_original_ms"] for record in measured]
        ),
        "reference_compiled_ms": _stats(
            [record["reference_compiled_ms"] for record in measured]
        ),
    }
    for field in ("accelerator_call_us", "roundtrip_ms"):
        summary[field] = _stats([
            record["qsim8"]["timing"][field]
            for record in measured
            if field in record.get("qsim8", {}).get("timing", {})
        ])
    summary["backend_run_ms"] = _stats([
        record["backend_run_ms"]
        for record in measured
        if "backend_run_ms" in record
    ])
    return summary


def _status(manifest):
    rows = manifest["tests"]
    repeats = manifest["configuration"]["repeats"]
    complete = (
        manifest["error"] is None
        and len(rows) == manifest["expected_case_count"]
        and all(len(row.get("measured", [])) == repeats for row in rows)
    )
    if not complete:
        return "INCOMPLETE"
    if manifest["mode"] == "reference_only":
        return "REFERENCE_ONLY"
    return "PASS" if all(row["status"] == "PASS" for row in rows) else "FAIL"


def _write_reports(folder, manifest):
    status = _status(manifest)
    manifest["status"] = status
    manifest["hardware_cases_passed"] = sum(
        row["status"] == "PASS" for row in manifest["tests"]
    )
    manifest["full_matrix_hardware_complete"] = (
        manifest["mode"] == "hardware"
        and manifest["configuration"]["full_matrix_selected"]
        and status == "PASS"
    )

    json_path = folder / "manifest.json"
    json_path.write_text(
        json.dumps(
            manifest,
            ensure_ascii=False,
            indent=2,
            default=_json_default,
            allow_nan=False,
        ),
        encoding="utf-8",
    )

    fields = [
        "case", "status", "num_qubits", "target_depth", "depth_original",
        "depth_compiled", "scheduled_depth", "gate_count", "native_instructions",
        "uart_total_bytes", "uart_ideal_ms", "measured_repeats",
        "max_error_worst", "fidelity_min", "norm_error_worst",
        "reference_median_ms", "accelerator_median_us",
        "roundtrip_median_ms", "roundtrip_p95_ms", "backend_median_ms",
    ]
    with (folder / "summary.csv").open("w", newline="", encoding="utf-8-sig") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        for row in manifest["tests"]:
            metrics = [
                record["metrics"]
                for record in row.get("measured", [])
                if "metrics" in record
            ]
            timing = _timing_summary(row)
            writer.writerow({
                "case": row["name"],
                "status": row["status"],
                "num_qubits": row["num_qubits"],
                "target_depth": row["target_depth"],
                "depth_original": row["depth_original"],
                "depth_compiled": row.get("depth_compiled"),
                "scheduled_depth": row.get("summary", {}).get("scheduled_depth"),
                "gate_count": row.get("summary", {}).get("gate_count"),
                "native_instructions": row.get("summary", {}).get("native_instructions"),
                "uart_total_bytes": row.get("uart_model", {}).get("total_bytes"),
                "uart_ideal_ms": row.get("uart_model", {}).get("ideal_8n1_ms"),
                "measured_repeats": len(row.get("measured", [])),
                "max_error_worst": max(
                    (metric["max_error"] for metric in metrics), default=None
                ),
                "fidelity_min": min(
                    (metric["fidelity"] for metric in metrics), default=None
                ),
                "norm_error_worst": max(
                    (metric["norm_error"] for metric in metrics), default=None
                ),
                "reference_median_ms": (
                    timing["reference_original_ms"] or {}
                ).get("median"),
                "accelerator_median_us": (
                    timing["accelerator_call_us"] or {}
                ).get("median"),
                "roundtrip_median_ms": (
                    timing["roundtrip_ms"] or {}
                ).get("median"),
                "roundtrip_p95_ms": (
                    timing["roundtrip_ms"] or {}
                ).get("p95"),
                "backend_median_ms": (
                    timing["backend_run_ms"] or {}
                ).get("median"),
            })

    full_case_count = len(QUBIT_GRID) * len(DEPTH_GRID)
    if manifest["configuration"]["full_matrix_selected"]:
        if manifest["mode"] == "hardware":
            matrix_line = (
                "- Hoàn tất ma trận phần cứng 8 × 5: **CÓ — 40/40 ca PASS**."
                if manifest["full_matrix_hardware_complete"]
                else "- Hoàn tất ma trận phần cứng 8 × 5: **CHƯA — có ca chưa hoàn tất hoặc chưa PASS**."
            )
        else:
            matrix_line = (
                "- Phạm vi: **đủ 40/40 cấu hình trên PC**; chưa phải kết quả "
                "ma trận phần cứng."
            )
    else:
        matrix_line = (
            f"- Phạm vi: **tập con {manifest['expected_case_count']}/{full_case_count} "
            "cấu hình**. Trạng thái ma trận đầy đủ: **không áp dụng cho phiên này**."
        )

    lines = [
        "# QSim8Q — benchmark số qubit và độ sâu",
        "",
        f"- Trạng thái: **{status}**; chế độ: `{manifest['mode']}`.",
        f"- Qubit: `{manifest['configuration']['qubits']}`.",
        f"- Depth: `{manifest['configuration']['depths']}`.",
        f"- Số cấu hình: **{manifest['expected_case_count']}**; "
        f"đạt phần cứng: **{manifest['hardware_cases_passed']}**.",
        matrix_line,
        f"- Tham chiếu: `{manifest['configuration']['reference']}`; "
        f"warm-up `{manifest['configuration']['warmup']}`, "
        f"đo `{manifest['configuration']['repeats']}` lần/ca.",
        "",
        "REFERENCE_ONLY chỉ xác minh bộ sinh mạch, transpile và tham chiếu PC; "
        "không phải kết quả FPGA.",
        "",
        "| Ca | Qubit | Depth | Lệnh native | Emax lớn nhất | Fidelity nhỏ nhất | Enorm lớn nhất | Accelerator median (us) | Roundtrip median (ms) | Trạng thái |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---|",
    ]
    for row in manifest["tests"]:
        metrics = [
            record["metrics"]
            for record in row.get("measured", [])
            if "metrics" in record
        ]
        timing = _timing_summary(row)
        prefix = (
            f"| {row['name']} | {row['num_qubits']} | {row['target_depth']} | "
            f"{row.get('summary', {}).get('native_instructions', '-')} | "
        )
        if metrics:
            emax = max(metric["max_error"] for metric in metrics)
            fidelity = min(metric["fidelity"] for metric in metrics)
            enorm = max(metric["norm_error"] for metric in metrics)
            accelerator = (timing["accelerator_call_us"] or {}).get("median")
            roundtrip = (timing["roundtrip_ms"] or {}).get("median")
            lines.append(
                prefix
                + f"{emax:.6e} | {fidelity:.12f} | {enorm:.6e} | "
                + f"{accelerator:.3f} | {roundtrip:.3f} | {row['status']} |"
            )
        else:
            lines.append(prefix + f"- | - | - | - | - | {row['status']} |")
    lines.extend([
        "",
        "## Cách đọc số liệu",
        "",
        "- Mỗi ca phải có đúng `2^num_qubits` biên độ.",
        "- Tiêu chí phần cứng: Emax ≤ 1e-2, fidelity ≥ 0.99 và "
        "|norm² − 1| ≤ 1e-2 cho mọi lần đo.",
        "- `accelerator_call_us` là timer ARM quanh lời gọi IP; "
        "`roundtrip_ms` gồm truyền UART; `backend_run_ms` là thời gian lời gọi BackendV2.",
        "- Mô hình UART dùng 115200 baud, 8N1: tổng byte = "
        "60 + 16×m + 8×2^n, với m là số lệnh native.",
        "- Tài nguyên LUT/FF/DSP/BRAM không đổi theo mạch; xem báo cáo HLS/Vivado riêng.",
        "- Hash file cục bộ cần đi cùng log nạp bo của phiên đo khi dùng làm bằng chứng.",
    ])
    if manifest["error"]:
        lines.extend(["", "## Lỗi", "", "```text", manifest["error"], "```"])
    (folder / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return json_path


def _publish_latest(folder, output_root):
    """Tạo các file ổn định để luôn mở đúng kết quả mới nhất."""
    output_root.mkdir(parents=True, exist_ok=True)
    for source_name, latest_name in (
        ("manifest.json", "latest_manifest.json"),
        ("summary.csv", "latest_summary.csv"),
        ("report.md", "latest_report.md"),
    ):
        shutil.copyfile(folder / source_name, output_root / latest_name)
    (output_root / "LATEST.txt").write_text(
        f"{folder.name}\n{folder}\n", encoding="utf-8"
    )


def _selection(values, low, high, label, parser):
    selected = tuple(sorted(set(values)))
    if not selected or any(value < low or value > high for value in selected):
        parser.error(f"{label} phai nam trong {low}..{high}")
    return selected


def _parser():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--hardware", action="store_true", help="Ket noi va chay tren Zybo"
    )
    mode.add_argument(
        "--reference-only",
        action="store_true",
        help="Chi tao tham chieu tren PC; day la che do mac dinh",
    )
    parser.add_argument("--port", help="Bat buoc khi --hardware, vi du COM14")
    parser.add_argument(
        "--reference", choices=("aer", "statevector"), default="aer"
    )
    parser.add_argument("--repeats", type=int, default=20)
    parser.add_argument("--warmup", type=int, default=2)
    parser.add_argument("--qubits", nargs="+", type=int, default=list(QUBIT_GRID))
    parser.add_argument("--depths", nargs="+", type=int, default=list(DEPTH_GRID))
    parser.add_argument(
        "--output", type=Path, default=ROOT / "results" / "scaling_benchmark"
    )
    return parser


def main(argv=None):
    parser = _parser()
    invocation_args = list(sys.argv[1:] if argv is None else argv)
    args = parser.parse_args(invocation_args)
    if args.hardware and not args.port:
        parser.error("--hardware requires --port COM14 (or the actual port)")
    if args.repeats < 1 or args.warmup < 0:
        parser.error("--repeats must be positive and --warmup must be non-negative")

    qubits = _selection(args.qubits, 1, MAX_QUBITS, "--qubits", parser)
    depths = _selection(args.depths, 1, MAX_LAYERS, "--depths", parser)
    full_matrix = qubits == QUBIT_GRID and depths == DEPTH_GRID
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    output_root = args.output.resolve()
    folder = output_root / (
        f"{stamp}_{'hardware' if args.hardware else 'reference'}"
    )
    folder.mkdir(parents=True, exist_ok=False)
    (folder / "circuits").mkdir()

    manifest = {
        "schema_version": "qsim8.scaling_benchmark.v1",
        "started_utc": _utc(),
        "finished_utc": None,
        "mode": "hardware" if args.hardware else "reference_only",
        "invocation": {
            "executable": sys.executable,
            "module": "qsim8_backend.benchmark_scaling",
            "arguments": invocation_args,
            "working_directory": str(Path.cwd().resolve()),
        },
        "configuration": {
            "port": args.port if args.hardware else None,
            "reference": args.reference,
            "repeats": args.repeats,
            "warmup": args.warmup,
            "qubits": list(qubits),
            "depths": list(depths),
            "full_matrix_selected": full_matrix,
            "generator": GENERATOR_VERSION,
            "transpile_optimization_level": 0,
            "seed_transpiler": SEED_TRANSPILER,
            "aer_method": "statevector" if args.reference == "aer" else None,
            "aer_precision": "double" if args.reference == "aer" else None,
            "aer_max_parallel_threads": 1 if args.reference == "aer" else None,
            "uart_baud": 115200,
            "uart_framing": "8N1",
        },
        "criteria": {
            "max_error": 1e-2,
            "fidelity_min": 0.99,
            "norm_error": 1e-2,
            "amplitude_count": "2**num_qubits",
            "execution_source": "serial_qsim8",
            "crc_validated": True,
        },
        "environment": _versions(),
        "provenance": {},
        "expected_case_count": len(qubits) * len(depths),
        "tests": [],
        "error": None,
        "failure_diagnostics": None,
    }

    backend = None
    active_row = None
    try:
        manifest["provenance"] = _provenance()
        evaluate = _make_reference(args.reference)
        backend = _backend_factory(args.port if args.hardware else None)
        circuits = scaling_circuits(qubits, depths)
        if args.hardware:
            backend.connect()

        for circuit in circuits:
            target_depth = circuit.metadata["target_depth"]
            active_row = {
                "name": circuit.name,
                "suite": "scaling",
                "num_qubits": circuit.num_qubits,
                "target_depth": target_depth,
                "depth_original": circuit.depth(),
                "status": "INCOMPLETE",
                "warmup": [],
                "measured": [],
            }
            manifest["tests"].append(active_row)

            compiled = transpile(
                circuit,
                backend=backend,
                optimization_level=0,
                seed_transpiler=SEED_TRANSPILER,
            )
            code = backend.compile(compiled)
            depth_compiled = compiled.depth()
            scheduled_depth = code.summary["scheduled_depth"]
            native_instructions = code.summary["native_instructions"]
            if depth_compiled != target_depth or scheduled_depth != target_depth:
                raise RuntimeError(
                    f"{circuit.name}: depth doi sau transpile/lap lich: "
                    f"original={circuit.depth()}, compiled={depth_compiled}, "
                    f"scheduled={scheduled_depth}, target={target_depth}."
                )
            if native_instructions > MAX_INSTRUCTIONS:
                raise RuntimeError(
                    f"{circuit.name}: {native_instructions} native instructions "
                    f"vuot {MAX_INSTRUCTIONS}."
                )

            total_bytes = 60 + 16 * native_instructions + 8 * (1 << circuit.num_qubits)
            active_row.update(
                depth_compiled=depth_compiled,
                summary=code.summary,
                global_phase=float(code.global_phase),
                global_phase_original=float(circuit.global_phase),
                instruction_hex=code.instructions.hex(),
                instruction_sha256=hashlib.sha256(code.instructions).hexdigest(),
                uart_model={
                    "formula": "60 + 16*m + 8*(2**n)",
                    "total_bytes": total_bytes,
                    "ideal_8n1_ms": 1000 * 10 * total_bytes / 115200,
                },
            )
            for tag, value in (("original", circuit), ("compiled", compiled)):
                relative = Path("circuits") / f"{circuit.name}_{tag}.qasm"
                (folder / relative).write_text(qasm3.dumps(value), encoding="utf-8")
                active_row[f"qasm_{tag}"] = relative.as_posix()

            for index in range(args.warmup + args.repeats):
                is_warmup = index < args.warmup
                expected, original_ms = evaluate(circuit)
                expected_compiled, compiled_ms = evaluate(compiled)
                transpile_error = (
                    float(np.max(np.abs(expected - expected_compiled)))
                    if expected.shape == expected_compiled.shape
                    else None
                )
                if (
                    transpile_error is None
                    or not np.isfinite(transpile_error)
                    or transpile_error > 1e-10
                ):
                    raise RuntimeError(
                        f"{circuit.name}: transpile doi state-vector: "
                        f"{transpile_error}"
                    )

                record = {
                    "index": index if is_warmup else index - args.warmup,
                    "started_utc": _utc(),
                    "reference_original_ms": original_ms,
                    "reference_compiled_ms": compiled_ms,
                    "transpile_max_error": transpile_error,
                    "reference_statevector": _state_pairs(expected),
                    "compiled_reference_statevector": _state_pairs(expected_compiled),
                }
                active_row["warmup" if is_warmup else "measured"].append(record)

                if args.hardware:
                    start = time.perf_counter()
                    job = backend.run(compiled)
                    result = job.result()
                    record["backend_run_ms"] = (time.perf_counter() - start) * 1000
                    actual = np.asarray(
                        result.get_statevector(compiled), dtype=np.complex128
                    )
                    metadata = getattr(result.results[0], "metadata", {})
                    qsim8 = metadata.get("qsim8", {})
                    if qsim8.get("execution_source") != "serial_qsim8":
                        raise RuntimeError(
                            f"{circuit.name}: thieu execution_source=serial_qsim8."
                        )
                    if qsim8.get("transaction", {}).get("crc_validated") is not True:
                        raise RuntimeError(f"{circuit.name}: CRC UART khong hop le.")
                    if actual.shape != (1 << circuit.num_qubits,):
                        raise RuntimeError(
                            f"{circuit.name}: nhan {actual.size} amplitude, "
                            f"can {1 << circuit.num_qubits}."
                        )
                    record.update(
                        hardware_statevector=_state_pairs(actual),
                        qsim8=qsim8,
                        metrics=compare(actual, expected),
                        job_id=job.job_id(),
                    )
                    if is_warmup and not record["metrics"]["pass"]:
                        raise RuntimeError(
                            f"{circuit.name}: warm-up khong dat nguong do chinh xac."
                        )

            active_row["timing_summary"] = _timing_summary(active_row)
            active_row["status"] = (
                "PASS"
                if args.hardware
                and all(record["metrics"]["pass"] for record in active_row["measured"])
                else "FAIL" if args.hardware else "REFERENCE_ONLY"
            )
            if args.hardware:
                metrics = [record["metrics"] for record in active_row["measured"]]
                timing = active_row["timing_summary"]
                print(
                    f"{circuit.name}: {active_row['status']} | "
                    f"native={native_instructions} | "
                    f"Emax={max(item['max_error'] for item in metrics):.6e} | "
                    f"Fmin={min(item['fidelity'] for item in metrics):.12f} | "
                    f"Enorm={max(item['norm_error'] for item in metrics):.6e} | "
                    f"accelerator_med={timing['accelerator_call_us']['median']:.3f} us | "
                    f"roundtrip_med={timing['roundtrip_ms']['median']:.3f} ms",
                    flush=True,
                )
            else:
                print(
                    f"{circuit.name}: REFERENCE_ONLY "
                    f"(native={native_instructions})",
                    flush=True,
                )
            _write_reports(folder, manifest)
        active_row = None
    except (Exception, KeyboardInterrupt) as exc:
        manifest["error"] = f"{type(exc).__name__}: {exc}"
        if backend is not None and hasattr(backend, "diagnostics"):
            try:
                manifest["failure_diagnostics"] = backend.diagnostics()
            except Exception as diagnostic_error:
                manifest["failure_diagnostics"] = {
                    "collection_error": (
                        f"{type(diagnostic_error).__name__}: {diagnostic_error}"
                    )
                }
        if active_row is not None:
            active_row["status"] = "ERROR"
            active_row["error"] = manifest["error"]
        print("BENCHMARK_ERROR:", manifest["error"], flush=True)
    finally:
        if backend is not None:
            try:
                backend.close()
            except Exception as close_error:
                if manifest["error"] is None:
                    manifest["error"] = (
                        f"{type(close_error).__name__}: {close_error}"
                    )
        manifest["finished_utc"] = _utc()
        output = _write_reports(folder, manifest)
        _publish_latest(folder, output_root)
        print("Saved:", output, flush=True)
        print("Latest report:", output_root / "latest_report.md", flush=True)

    return 0 if manifest["status"] in {"PASS", "REFERENCE_ONLY"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
