"""Tạo biểu đồ và báo cáo tổng hợp từ manifest benchmark phần cứng QSim8Q."""
import argparse
import hashlib
import json
import math
import os
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MPL_CACHE = ROOT / ".cache" / "matplotlib"
MPL_CACHE.mkdir(parents=True, exist_ok=True)
os.environ.setdefault("MPLCONFIGDIR", str(MPL_CACHE))

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np


DEPTHS = (1, 5, 10, 15, 20)
QUBITS = tuple(range(1, 9))
EMAX_LIMIT = 1e-2
FIDELITY_LIMIT = 0.99
ENORM_LIMIT = 1e-2
COLORS = plt.cm.viridis(np.linspace(0.05, 0.95, len(QUBITS)))


def _load(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _stats(values):
    values = list(values)
    if not values:
        return None
    return {
        "count": len(values),
        "median": float(np.median(values)),
        "p95": float(np.percentile(values, 95)),
        "min": float(min(values)),
        "max": float(max(values)),
    }


def _row(test):
    measured = [record for record in test.get("measured", []) if "metrics" in record]
    metrics = [record["metrics"] for record in measured]
    timing = [record.get("qsim8", {}).get("timing", {}) for record in measured]
    transaction = [record.get("qsim8", {}).get("transaction", {}) for record in measured]
    sources = [record.get("qsim8", {}).get("execution_source") for record in measured]
    native = int(test.get("summary", {}).get("native_instructions", 0))
    qubits = int(test["num_qubits"])
    total_bytes = 60 + 16 * native + 8 * (1 << qubits)
    return {
        "name": test["name"],
        "suite": test.get("suite"),
        "status": test["status"],
        "num_qubits": qubits,
        "depth": int(test.get("target_depth", test.get("depth_original", 0))),
        "native_instructions": native,
        "repeats": len(measured),
        "emax_worst": max((float(item["max_error"]) for item in metrics), default=math.nan),
        "fidelity_min": min((float(item["fidelity"]) for item in metrics), default=math.nan),
        "enorm_worst": max((float(item["norm_error"]) for item in metrics), default=math.nan),
        "reference_ms": _stats(
            float(record["reference_original_ms"]) for record in measured
        ),
        "accelerator_us": _stats(
            float(item["accelerator_call_us"])
            for item in timing if "accelerator_call_us" in item
        ),
        "roundtrip_ms": _stats(
            float(item["roundtrip_ms"])
            for item in timing if "roundtrip_ms" in item
        ),
        "backend_ms": _stats(
            float(record["backend_run_ms"])
            for record in measured if "backend_run_ms" in record
        ),
        "uart_total_bytes": total_bytes,
        "uart_ideal_ms": 1000 * 10 * total_bytes / 115200,
        "all_serial": bool(measured) and all(source == "serial_qsim8" for source in sources),
        "all_crc": bool(measured) and all(item.get("crc_validated") is True for item in transaction),
    }


def _style_axis(axis, title, xlabel, ylabel, log=False):
    axis.set_title(title, fontweight="bold", pad=12)
    axis.set_xlabel(xlabel)
    axis.set_ylabel(ylabel)
    axis.grid(True, which="both", linestyle="--", alpha=0.28)
    axis.set_xticks(DEPTHS)
    if log:
        axis.set_yscale("log")


def _save(figure, folder, name):
    figure.tight_layout()
    png = folder / f"{name}.png"
    svg = folder / f"{name}.svg"
    figure.savefig(png, dpi=180, bbox_inches="tight", facecolor="white")
    figure.savefig(svg, bbox_inches="tight", facecolor="white")
    plt.close(figure)
    return png


def _line_chart(rows, field, statistic, title, ylabel, folder, name, log=False,
                limit=None):
    figure, axis = plt.subplots(figsize=(10.5, 6.2))
    for qubit, color in zip(QUBITS, COLORS):
        selected = sorted(
            (row for row in rows if row["num_qubits"] == qubit),
            key=lambda row: row["depth"],
        )
        if not selected:
            continue
        values = []
        for row in selected:
            value = row[field]
            if statistic is not None:
                value = value[statistic] if value else math.nan
            if log and value <= 0:
                value = 1e-18
            values.append(value)
        axis.plot(
            [row["depth"] for row in selected], values,
            marker="o", linewidth=1.8, markersize=4.5,
            label=f"{qubit} qubit", color=color,
        )
    if limit is not None:
        axis.axhline(limit, color="#c62828", linestyle="--", linewidth=1.4,
                     label=f"Ngưỡng {limit:g}")
    _style_axis(axis, title, "Độ sâu mạch", ylabel, log=log)
    axis.legend(ncol=2, fontsize=8, frameon=True)
    return _save(figure, folder, name)


def _fidelity_chart(rows, folder):
    figure, axis = plt.subplots(figsize=(10.5, 6.2))
    minimum = []
    for qubit in QUBITS:
        values = [row["fidelity_min"] for row in rows if row["num_qubits"] == qubit]
        minimum.append(min(values) if values else math.nan)
    infidelity = [max(1e-18, 1 - value) for value in minimum]
    bars = axis.bar(QUBITS, infidelity, color=COLORS, edgecolor="#263238", linewidth=0.5)
    axis.set_yscale("log")
    axis.set_title("Fidelity nhỏ nhất theo số qubit", fontweight="bold", pad=12)
    axis.set_xlabel("Số qubit")
    axis.set_ylabel("1 − Fmin (thang log; càng thấp càng tốt)")
    axis.grid(True, axis="y", which="both", linestyle="--", alpha=0.28)
    threshold = 1 - FIDELITY_LIMIT
    axis.axhline(threshold, color="#c62828", linestyle="--", linewidth=1.4,
                 label="Ngưỡng thuyết minh: F ≥ 0,99")
    for bar, fidelity in zip(bars, minimum):
        axis.annotate(
            f"1−F={max(0.0, 1 - fidelity):.2e}",
            (bar.get_x() + bar.get_width() / 2, bar.get_height()),
            xytext=(0, 5), textcoords="offset points", ha="center",
            va="bottom", fontsize=7, rotation=35,
        )
    axis.legend(fontsize=8)
    return _save(figure, folder, "05_fidelity_min_by_qubit")


def _uart_chart(rows, folder):
    figure, axis = plt.subplots(figsize=(10.5, 6.2))
    for qubit, color in zip(QUBITS, COLORS):
        selected = [row for row in rows if row["num_qubits"] == qubit]
        if not selected:
            continue
        axis.scatter(
            [row["uart_ideal_ms"] for row in selected],
            [row["roundtrip_ms"]["median"] for row in selected],
            label=f"{qubit} qubit", color=color, s=42, alpha=0.9,
            edgecolors="white", linewidths=0.5,
        )
    maximum = max(
        max(row["uart_ideal_ms"], row["roundtrip_ms"]["median"]) for row in rows
    )
    axis.plot([0, maximum * 1.03], [0, maximum * 1.03], "--",
              color="#c62828", linewidth=1.3, label="Thực tế = lý tưởng")
    axis.set_title("UART roundtrip thực tế và giới hạn truyền 115200 baud",
                   fontweight="bold", pad=12)
    axis.set_xlabel("Thời gian truyền lý tưởng 8N1 (ms)")
    axis.set_ylabel("Roundtrip median đo được (ms)")
    axis.grid(True, linestyle="--", alpha=0.28)
    axis.legend(ncol=2, fontsize=8)
    return _save(figure, folder, "06_uart_actual_vs_ideal")


def create_charts(rows, folder):
    folder.mkdir(parents=True, exist_ok=True)
    plt.rcParams.update({
        "font.family": "DejaVu Sans",
        "font.size": 10,
        "axes.spines.top": False,
        "axes.spines.right": False,
    })
    files = [
        _line_chart(
            rows, "accelerator_us", "median",
            "Thời gian accelerator theo số qubit và độ sâu",
            "Accelerator median (µs)", folder, "01_accelerator_vs_depth",
        ),
        _line_chart(
            rows, "roundtrip_ms", "median",
            "UART roundtrip theo số qubit và độ sâu",
            "Roundtrip median (ms)", folder, "02_roundtrip_vs_depth",
        ),
        _line_chart(
            rows, "emax_worst", None,
            "Sai số biên độ cực đại theo độ sâu",
            "Emax xấu nhất", folder, "03_emax_vs_depth", log=True,
            limit=EMAX_LIMIT,
        ),
        _line_chart(
            rows, "enorm_worst", None,
            "Sai số chuẩn hóa theo độ sâu",
            "Enorm xấu nhất", folder, "04_enorm_vs_depth", log=True,
            limit=ENORM_LIMIT,
        ),
        _fidelity_chart(rows, folder),
        _uart_chart(rows, folder),
    ]
    return files


def _fmt(value, digits=3):
    return f"{value:.{digits}f}"


def _md_row(row):
    return (
        f"| {row['name']} | {row['num_qubits']} | {row['depth']} | "
        f"{row['native_instructions']} | {row['emax_worst']:.6e} | "
        f"{row['fidelity_min']:.15f} | {row['enorm_worst']:.6e} | "
        f"{row['accelerator_us']['median']:.3f} | "
        f"{row['roundtrip_ms']['median']:.3f} | {row['status']} |"
    )


def generate_report(scaling_manifest, acceptance_manifest, loader_log, output):
    scaling_path = Path(scaling_manifest).resolve()
    acceptance_path = Path(acceptance_manifest).resolve()
    loader_path = Path(loader_log).resolve()
    output = Path(output).resolve()
    output.mkdir(parents=True, exist_ok=True)
    charts_dir = output / "charts"

    scaling = _load(scaling_path)
    acceptance = _load(acceptance_path)
    scaling_rows = [_row(test) for test in scaling["tests"]]
    stress_rows = [_row(test) for test in acceptance["tests"] if test.get("suite") == "stress"]
    chart_files = create_charts(scaling_rows, charts_dir)

    measured = sum(row["repeats"] for row in scaling_rows)
    emax_row = max(scaling_rows, key=lambda row: row["emax_worst"])
    fidelity_row = min(scaling_rows, key=lambda row: row["fidelity_min"])
    enorm_row = max(scaling_rows, key=lambda row: row["enorm_worst"])
    first = next(row for row in scaling_rows if row["num_qubits"] == 1 and row["depth"] == 1)
    last = next(row for row in scaling_rows if row["num_qubits"] == 8 and row["depth"] == 20)
    accelerator_ratio = last["accelerator_us"]["median"] / first["accelerator_us"]["median"]
    roundtrip_ratio = last["roundtrip_ms"]["median"] / first["roundtrip_ms"]["median"]
    work = np.asarray([
        row["native_instructions"] * (1 << row["num_qubits"])
        for row in scaling_rows
    ], dtype=float)
    accelerator = np.asarray([
        row["accelerator_us"]["median"] for row in scaling_rows
    ], dtype=float)
    uart_ideal = np.asarray([row["uart_ideal_ms"] for row in scaling_rows], dtype=float)
    roundtrip = np.asarray([
        row["roundtrip_ms"]["median"] for row in scaling_rows
    ], dtype=float)
    accelerator_corr = float(np.corrcoef(work, accelerator)[0, 1])
    uart_corr = float(np.corrcoef(uart_ideal, roundtrip)[0, 1])
    uart_actual_to_ideal = roundtrip / uart_ideal
    roundtrip_to_accelerator = roundtrip * 1000.0 / accelerator

    loader_text = loader_path.read_text(encoding="utf-8", errors="replace")
    loader_markers = {
        marker: marker in loader_text
        for marker in ("ROUTED_TIMING_OK", "UART_READY", "APPLICATION_RUNNING")
    }
    scaling_complete = (
        scaling.get("mode") == "hardware"
        and scaling.get("full_matrix_hardware_complete") is True
        and len(scaling_rows) == 40
        and all(row["status"] == "PASS" and row["all_serial"] and row["all_crc"] for row in scaling_rows)
    )
    stress_complete = (
        len(stress_rows) == 3
        and all(row["status"] == "PASS" and row["all_serial"] and row["all_crc"] for row in stress_rows)
    )
    loader_complete = all(loader_markers.values())
    final_status = "PASS" if scaling_complete and stress_complete and loader_complete else "INCOMPLETE"

    copied_scaling = output / "scaling_manifest.json"
    copied_acceptance = output / "acceptance_stress_manifest.json"
    copied_loader = output / "board_load.log"
    if scaling_path != copied_scaling:
        shutil.copyfile(scaling_path, copied_scaling)
    if acceptance_path != copied_acceptance:
        shutil.copyfile(acceptance_path, copied_acceptance)
    if loader_path != copied_loader:
        shutil.copyfile(loader_path, copied_loader)

    lines = [
        "# QSim8Q — báo cáo benchmark chính thức trên Zybo",
        "",
        f"> **Kết luận phiên đo: {final_status}.** Ma trận scaling: "
        f"{'40/40 PASS' if scaling_complete else 'chưa đủ'}; stress: "
        f"{'3/3 PASS' if stress_complete else 'chưa đủ'}; log nạp bo: "
        f"{'đủ dấu mốc' if loader_complete else 'thiếu dấu mốc'}.",
        "",
        "## 1. Cấu hình và phương pháp",
        "",
        f"- Thời gian bắt đầu scaling: `{scaling.get('started_utc')}`; hoàn tất: `{scaling.get('finished_utc')}`.",
        f"- Phạm vi: 1–8 qubit; depth 1, 5, 10, 15, 20; tổng 40 cấu hình.",
        f"- Mỗi cấu hình: `{scaling['configuration']['repeats']}` lần đo và `{scaling['configuration']['warmup']}` warm-up.",
        f"- Tổng số lần đo scaling chính thức: **{measured}**.",
        f"- Tham chiếu: Qiskit Aer `{scaling['configuration']['aer_method']}`, precision `{scaling['configuration']['aer_precision']}`, một luồng.",
        f"- Transpile: optimization level `{scaling['configuration']['transpile_optimization_level']}`, seed `{scaling['configuration']['seed_transpiler']}`.",
        f"- Scaling có `serial_qsim8` và CRC hợp lệ cho mọi lần đo: **{all(row['all_serial'] and row['all_crc'] for row in scaling_rows)}**.",
        "",
        "## 2. Kết quả độ chính xác",
        "",
        "| Chỉ tiêu | Ngưỡng | Kết quả xấu nhất | Ca tương ứng | Đánh giá |",
        "|---|---:|---:|---|---|",
        f"| Emax | ≤ {EMAX_LIMIT:g} | {emax_row['emax_worst']:.6e} | {emax_row['name']} | {'PASS' if emax_row['emax_worst'] <= EMAX_LIMIT else 'FAIL'} |",
        f"| Fidelity | ≥ {FIDELITY_LIMIT:g} | {fidelity_row['fidelity_min']:.15f} | {fidelity_row['name']} | {'PASS' if fidelity_row['fidelity_min'] >= FIDELITY_LIMIT else 'FAIL'} |",
        f"| Enorm | ≤ {ENORM_LIMIT:g} | {enorm_row['enorm_worst']:.6e} | {enorm_row['name']} | {'PASS' if enorm_row['enorm_worst'] <= ENORM_LIMIT else 'FAIL'} |",
        "",
        "Sai số tăng nhẹ khi số phép cập nhật state-vector tăng, nhưng trường hợp xấu nhất vẫn thấp hơn ngưỡng Emax hơn "
        f"**{EMAX_LIMIT / emax_row['emax_worst']:.2e} lần**. Fidelity nhỏ nhất vẫn gần 1; dấu vết sai số ở cỡ 10⁻⁹–10⁻⁸ phù hợp với tích lũy lượng tử hóa Q2.30.",
        "",
        "![Emax theo depth](charts/03_emax_vs_depth.png)",
        "",
        "![Enorm theo depth](charts/04_enorm_vs_depth.png)",
        "",
        "![Fidelity theo qubit](charts/05_fidelity_min_by_qubit.png)",
        "",
        "## 3. Hiệu năng và khả năng mở rộng",
        "",
        f"- Accelerator median tăng từ **{first['accelerator_us']['median']:.3f} µs** ở 1Q/1L lên **{last['accelerator_us']['median']:.3f} µs** ở 8Q/20L, tương đương **{accelerator_ratio:.1f}×**.",
        f"- Roundtrip median tăng từ **{first['roundtrip_ms']['median']:.3f} ms** lên **{last['roundtrip_ms']['median']:.3f} ms**, tương đương **{roundtrip_ratio:.1f}×**.",
        f"- Tương quan giữa proxy `native_instructions × 2^n` và accelerator median là **{accelerator_corr:.4f}**.",
        f"- Tương quan giữa thời gian UART lý tưởng và roundtrip đo được là **{uart_corr:.4f}**.",
        f"- Roundtrip/giới hạn truyền lý tưởng có median **{np.median(uart_actual_to_ideal):.3f}×**, "
        f"dao động **{np.min(uart_actual_to_ideal):.3f}–{np.max(uart_actual_to_ideal):.3f}×**.",
        "",
        "![Accelerator theo depth](charts/01_accelerator_vs_depth.png)",
        "",
        "![Roundtrip theo depth](charts/02_roundtrip_vs_depth.png)",
        "",
        "![UART thực tế và lý tưởng](charts/06_uart_actual_vs_ideal.png)",
        "",
        "## 4. Phân tích điểm nghẽn",
        "",
        "- Khối lượng tính toán của lõi tăng theo số lệnh và số biên độ 2^n; xu hướng accelerator phù hợp với proxy này.",
        f"- Roundtrip lớn hơn thời gian accelerator **{np.min(roundtrip_to_accelerator):.0f}–{np.max(roundtrip_to_accelerator):.0f} lần** trong ma trận đo. Với giao thức hiện tại, truyền state-vector Q2.30 ở 115200 baud là điểm nghẽn hệ thống khi n tăng.",
        "- Roundtrip bám sát mô hình UART lý tưởng chứng tỏ phần lớn thời gian phía người dùng đến từ số byte trên đường truyền, không phải riêng phép tính PL.",
        "- Không dùng accelerator time chia cho thời gian Aer để tuyên bố speedup toàn hệ thống; hai đại lượng có phạm vi đo khác nhau.",
        "",
        "## 5. Stress 20 lớp",
        "",
        "| Ca | Qubit | Depth | Lệnh native | Emax | Fidelity min | Enorm | Accelerator median (µs) | Roundtrip median (ms) | Trạng thái |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---|",
    ]
    lines.extend(_md_row(row) for row in stress_rows)
    lines.extend([
        "",
        "Ba ca stress kiểm tra hai tải dense ở 1 và 8 qubit cùng tải SWAP 8 qubit sát giới hạn lệnh sau phân rã. Chúng bổ sung kiểm tra biên, không thay đổi mẫu số 15 ca nghiệm thu chức năng.",
        "",
        "## 6. Bảng 40 cấu hình",
        "",
        "| Ca | Qubit | Depth | Lệnh native | Emax | Fidelity min | Enorm | Accelerator median (µs) | Roundtrip median (ms) | Trạng thái |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---|",
    ])
    lines.extend(_md_row(row) for row in scaling_rows)
    lines.extend([
        "",
        "## 7. Truy nguyên và giới hạn kết luận",
        "",
        f"- Manifest scaling: [`scaling_manifest.json`](scaling_manifest.json), SHA-256 `{_sha256(copied_scaling)}`.",
        f"- Manifest nghiệm thu/stress: [`acceptance_stress_manifest.json`](acceptance_stress_manifest.json), SHA-256 `{_sha256(copied_acceptance)}`.",
        f"- Log nạp bo: [`board_load.log`](board_load.log), SHA-256 `{_sha256(copied_loader)}`.",
        f"- Dấu mốc loader: `{loader_markers}`.",
        "- Kết luận áp dụng cho bitstream, ELF, mã nguồn, môi trường và bộ mạch có hash trong hai manifest; không suy rộng thành mọi mạch 8 qubit có thể có.",
        "- Ma trận MIXED làm tăng đồng thời số biên độ và số cổng khi tăng qubit; nó đo tải hệ thống tổng hợp, không cô lập riêng chi phí một cổng.",
        "- Số liệu HLS/Vivado về LUT, FF, DSP, BRAM và routed timing được báo cáo riêng; tài nguyên không thay đổi theo mạch runtime.",
    ])
    report_path = output / "final_report.md"
    report_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    summary = {
        "schema_version": "qsim8.final_benchmark.v1",
        "status": final_status,
        "scaling": {
            "complete": scaling_complete,
            "cases": len(scaling_rows),
            "measured_records": measured,
            "emax_worst": emax_row["emax_worst"],
            "fidelity_min": fidelity_row["fidelity_min"],
            "enorm_worst": enorm_row["enorm_worst"],
            "accelerator_ratio_8q20_to_1q1": accelerator_ratio,
            "roundtrip_ratio_8q20_to_1q1": roundtrip_ratio,
            "work_accelerator_correlation": accelerator_corr,
            "uart_roundtrip_correlation": uart_corr,
            "uart_actual_to_ideal_ratio": {
                "min": float(np.min(uart_actual_to_ideal)),
                "median": float(np.median(uart_actual_to_ideal)),
                "max": float(np.max(uart_actual_to_ideal)),
            },
            "roundtrip_to_accelerator_ratio": {
                "min": float(np.min(roundtrip_to_accelerator)),
                "median": float(np.median(roundtrip_to_accelerator)),
                "max": float(np.max(roundtrip_to_accelerator)),
            },
        },
        "stress": {"complete": stress_complete, "cases": len(stress_rows)},
        "loader": {"complete": loader_complete, "markers": loader_markers},
        "artifacts": {
            "report": str(report_path),
            "charts": [str(path) for path in chart_files],
            "scaling_manifest_sha256": _sha256(copied_scaling),
            "acceptance_manifest_sha256": _sha256(copied_acceptance),
            "loader_log_sha256": _sha256(copied_loader),
        },
    }
    summary_path = output / "final_summary.json"
    summary_path.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return report_path, summary_path


def main(argv=None):
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scaling-manifest", type=Path, required=True)
    parser.add_argument("--acceptance-manifest", type=Path, required=True)
    parser.add_argument("--loader-log", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    report, summary = generate_report(
        args.scaling_manifest, args.acceptance_manifest,
        args.loader_log, args.output,
    )
    print("FINAL_REPORT:", report)
    print("FINAL_SUMMARY:", summary)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
