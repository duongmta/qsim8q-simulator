from __future__ import annotations

import csv
import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
REPORTS = ROOT / "reports"
VERSIONS = [f"v{i}" for i in range(1, 7)]
RATIONALE = {
    "v1": "Tối ưu tự động của Vitis (pipeline_loops=64)",
    "v2": "Baseline kiểm soát, tắt auto/manual pipeline",
    "v3": "Pipeline thủ công, ép II=1",
    "v4": "Pipeline thủ công, để HLS chọn II",
    "v5": "Hai state buffer packed ping-pong",
    "v6": "Một state buffer packed in-place, II=2",
}


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def newest_report(version: str, filename: str) -> Path | None:
    # GUI components are normally stored as
    # build/gui_workspace/qsim8_v1/qsim8_v1/reports/..., while command-line
    # builds may use build/v1/.... Search both layouts and bind the report to
    # its version through a path component such as "v1" or "qsim8_v1".
    roots = [ROOT / "build", ROOT / version]
    candidates: list[Path] = []
    for folder in roots:
        if folder.exists():
            for path in folder.rglob(filename):
                if folder == ROOT / version:
                    belongs_to_version = True
                else:
                    # Only inspect components below build/. The suite folder
                    # itself contains the text "V1_V6" and must not be used
                    # as a version match.
                    parts = [part.lower() for part in path.relative_to(folder).parts]
                    belongs_to_version = any(
                        part == version
                        or part.endswith(f"_{version}")
                        or part.startswith(f"{version}_")
                        for part in parts
                    )
                if belongs_to_version:
                    candidates.append(path)
    return max(candidates, key=lambda p: p.stat().st_mtime) if candidates else None


def leading_number(cell: str) -> int | None:
    match = re.search(r"-?\d+", cell.replace(",", ""))
    return int(match.group(0)) if match else None


def parse_compile_report(path: Path | None) -> dict[str, object]:
    result: dict[str, object] = {
        "synthesis": "CHUA_CHAY",
        "slack_ns": None,
        "bram18k": None,
        "dsp": None,
        "ff": None,
        "lut": None,
        "uram": None,
        "latency_1q_cycles": None,
        "ii_1q": None,
        "latency_2q_cycles": None,
        "ii_2q": None,
        "compile_report": None,
        "compile_sha256": None,
    }
    if path is None:
        return result

    text = path.read_text(encoding="utf-8", errors="replace")
    result["compile_report"] = str(path.relative_to(ROOT))
    result["compile_sha256"] = sha256(path)

    for line in text.splitlines():
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if not cells:
            continue
        name = cells[0].lstrip("+").strip()
        # The report repeats the top name in several tables. The utilization
        # summary has 15 cells; shorter rows would overwrite resources with '-'.
        if name == "quantum_simulator" and len(cells) >= 15:
            resource = cells[-5:]
            result["bram18k"] = leading_number(resource[0])
            result["dsp"] = leading_number(resource[1])
            result["ff"] = leading_number(resource[2])
            result["lut"] = leading_number(resource[3])
            result["uram"] = leading_number(resource[4])
            try:
                result["slack_ns"] = float(cells[-6])
            except (ValueError, IndexError):
                result["slack_ns"] = None
            result["synthesis"] = "PASS"

        loop_name = cells[0].lstrip(" +o").strip()
        if loop_name in {"single_gate_loop", "controlled_gate_loop"} and len(cells) >= 5:
            latency = leading_number(cells[3])
            interval = leading_number(cells[4])
            if loop_name == "single_gate_loop":
                result["latency_1q_cycles"] = latency
                result["ii_1q"] = interval
            else:
                result["latency_2q_cycles"] = latency
                result["ii_2q"] = interval

    return result


def parse_cosim_report(path: Path | None) -> dict[str, object]:
    result: dict[str, object] = {
        "cosim": "CHUA_CHAY",
        "cosim_report": None,
        "cosim_sha256": None,
    }
    if path is None:
        return result
    text = path.read_text(encoding="utf-8", errors="replace")
    result["cosim_report"] = str(path.relative_to(ROOT))
    result["cosim_sha256"] = sha256(path)
    if re.search(r"\bPass\b", text, flags=re.IGNORECASE):
        result["cosim"] = "PASS"
    elif re.search(r"\bFail\b", text, flags=re.IGNORECASE):
        result["cosim"] = "FAIL"
    else:
        result["cosim"] = "KHONG_RO"
    return result


def source_manifest(version: str) -> dict[str, str]:
    folder = ROOT / version
    return {
        name: sha256(folder / name)
        for name in ("qsim_hls.h", "qsim_hls.cpp", "qsim_tb.cpp", "hls_config.cfg")
    }


def format_value(value: object) -> str:
    return "-" if value is None else str(value)


def percent_delta(value: object, baseline: object) -> str:
    if not isinstance(value, (int, float)) or not isinstance(baseline, (int, float)):
        return "-"
    if baseline == 0:
        return "-"
    return f"{100.0 * (value - baseline) / baseline:+.2f}%"


def main() -> int:
    REPORTS.mkdir(exist_ok=True)
    rows: list[dict[str, object]] = []
    manifests: dict[str, object] = {}

    for version in VERSIONS:
        compile_path = newest_report(version, "hls_compile.rpt")
        cosim_path = newest_report(version, "hls_cosim.rpt")
        row: dict[str, object] = {
            "version": version.upper(),
            "change": RATIONALE[version],
        }
        row.update(parse_compile_report(compile_path))
        row.update(parse_cosim_report(cosim_path))
        rows.append(row)
        functional_log = REPORTS / "functional_logs" / f"{version}.log"
        manifests[version] = {
            "sources": source_manifest(version),
            "host_functional_log": (
                str(functional_log.relative_to(ROOT)) if functional_log.exists() else None
            ),
            "host_functional_sha256": (
                sha256(functional_log) if functional_log.exists() else None
            ),
            "compile_report": row["compile_report"],
            "compile_sha256": row["compile_sha256"],
            "cosim_report": row["cosim_report"],
            "cosim_sha256": row["cosim_sha256"],
        }

    csv_path = REPORTS / "resource_comparison.csv"
    fields = [
        "version", "change", "synthesis", "cosim", "slack_ns",
        "bram18k", "dsp", "ff", "lut", "uram",
        "latency_1q_cycles", "ii_1q", "latency_2q_cycles", "ii_2q",
        "compile_report", "compile_sha256", "cosim_report", "cosim_sha256",
    ]
    with csv_path.open("w", newline="", encoding="utf-8-sig") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)

    md_lines = [
        "# So sánh tài nguyên HLS V1-V6",
        "",
        "Cấu hình chung: 8 qubit, Q2.30, 256 lệnh, xc7z010clg400-1, clock 10 ns, uncertainty 1 ns.",
        "",
        "| Bản | Thay đổi | Synthesis | RTL Cosim | Slack (ns) | BRAM18K | DSP | FF | LUT | Latency 1Q | II 1Q | Latency 2Q | II 2Q |",
        "|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for row in rows:
        md_lines.append(
            "| {version} | {change} | {synthesis} | {cosim} | {slack} | "
            "{bram} | {dsp} | {ff} | {lut} | {lat1} | {ii1} | {lat2} | {ii2} |".format(
                version=row["version"],
                change=row["change"],
                synthesis=row["synthesis"],
                cosim=row["cosim"],
                slack=format_value(row["slack_ns"]),
                bram=format_value(row["bram18k"]),
                dsp=format_value(row["dsp"]),
                ff=format_value(row["ff"]),
                lut=format_value(row["lut"]),
                lat1=format_value(row["latency_1q_cycles"]),
                ii1=format_value(row["ii_1q"]),
                lat2=format_value(row["latency_2q_cycles"]),
                ii2=format_value(row["ii_2q"]),
            )
        )

    md_lines.extend([
        "",
        "`CHUA_CHAY` nghĩa là chưa tìm thấy report mới trong workspace chuẩn hóa; không phải lỗi thuật toán.",
    ])

    baseline = rows[1]
    if baseline["synthesis"] == "PASS":
        md_lines.extend([
            "",
            "## Mức thay đổi tài nguyên so với V2 baseline",
            "",
            "| Bản | Delta BRAM18K | Delta DSP | Delta FF | Delta LUT |",
            "|---|---:|---:|---:|---:|",
        ])
        for row in rows:
            md_lines.append(
                "| {version} | {bram} | {dsp} | {ff} | {lut} |".format(
                    version=row["version"],
                    bram=percent_delta(row["bram18k"], baseline["bram18k"]),
                    dsp=percent_delta(row["dsp"], baseline["dsp"]),
                    ff=percent_delta(row["ff"], baseline["ff"]),
                    lut=percent_delta(row["lut"], baseline["lut"]),
                )
            )

    md_lines.extend([
        "",
        "## Quy tắc kết luận",
        "",
        "- Chỉ so sánh phần trăm khi cả hai phiên bản đều có report từ cùng Vitis 2026.1.",
        "- V2 là baseline kiểm soát.",
        "- V6 chỉ được kết luận phù hợp nhất khi C Sim/Cosim PASS, đủ tài nguyên và timing phù hợp.",
        "- Báo cáo tài nguyên cũ của 15 qubit/Zynq-7020 không được trộn vào bảng này.",
        "",
    ])
    (REPORTS / "resource_comparison.md").write_text("\n".join(md_lines), encoding="utf-8")

    manifest = {
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "controlled_configuration": {
            "part": "xc7z010clg400-1",
            "clock_ns": 10,
            "clock_uncertainty_ns": 1,
            "max_qubits": 8,
            "state_count": 256,
            "max_instructions": 256,
            "numeric_type": "Q2.30",
            "top": "quantum_simulator",
        },
        "versions": manifests,
    }
    (REPORTS / "evidence_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    print(f"WROTE: {csv_path}")
    print(f"WROTE: {REPORTS / 'resource_comparison.md'}")
    print(f"WROTE: {REPORTS / 'evidence_manifest.json'}")
    missing = [row["version"] for row in rows if row["synthesis"] != "PASS"]
    if missing:
        print("REPORTS_PENDING:", ", ".join(str(item) for item in missing))
    else:
        print("ALL_SYNTHESIS_REPORTS_FOUND")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
