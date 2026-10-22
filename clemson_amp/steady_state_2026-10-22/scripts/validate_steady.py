#!/usr/bin/env python3
"""Validate current native controlled-scenario fields and stationary identities."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import sys

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
from result_provenance import verify_model_result


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_native(path: Path) -> tuple[np.ndarray, list[str]]:
    numbers, labels = [], []
    for line in path.read_text().splitlines():
        if not line.strip() or line.lstrip().startswith("*"):
            continue
        fields = line.split()
        if len(fields) < 9:
            raise ValueError(f"Incomplete native result row: {path}")
        numbers.append([float(value.replace("D", "E")) for value in fields[:6]])
        labels.append(fields[8])
    values = np.asarray(numbers)
    if not np.isfinite(values).all() or np.any(values[:, 2] < 0):
        raise ValueError(f"Invalid native field: {path}")
    return values, labels


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args()
    project = args.project.resolve()
    scenario_file = project / "scenario.json"
    scenario = json.loads(scenario_file.read_text())
    count, hours = scenario["receptor_count"], scenario["hours"]
    report = {"created_utc": datetime.now(timezone.utc).isoformat(), "status": "in_progress",
              "scenario": {"path": str(scenario_file), "sha256": digest(scenario_file)},
              "script": {"path": str(Path(__file__).resolve()), "sha256": digest(Path(__file__))},
              "expected_cases": len(scenario["particle_cases"]), "expected_receptors": count,
              "expected_hours_per_case": hours, "case_metrics": {}}
    record = project / "model_validation.json"
    try:
        reference_coordinates = None
        for case in scenario["particle_cases"]:
            surface = (project / case["surface_file"]).read_text().splitlines()[1:]
            if len(surface) != hours:
                raise ValueError(f"Wrong surface-hour count: {case['name']}")
            surface_values = np.array([[float(value) for value in row.split()[:25]] for row in surface])
            if not np.array_equal(surface_values[:, 5:], np.repeat(surface_values[:1, 5:], hours, axis=0)):
                raise ValueError(f"Surface weather varies across hours: {case['name']}")
            profile_values = np.array([[float(value) for value in row.split()]
                                       for row in (project / case["profile_file"]).read_text().splitlines()])
            if len(profile_values) != hours or not np.array_equal(profile_values[:, 4:], np.repeat(profile_values[:1, 4:], hours, axis=0)):
                raise ValueError(f"Profile weather varies across hours: {case['name']}")
            for metric in ("concentration", "dry_deposition", "wet_deposition"):
                directory = project / "aermod" / case["name"] / metric
                period_file, hourly_file = directory / "annual.plt", directory / "hourly.plt"
                verification = verify_model_result(project, period_file)
                period, period_hours = read_native(period_file)
                hourly, timestamps = read_native(hourly_file)
                if len(period) != count or len(hourly) != count * hours:
                    raise ValueError(f"Unexpected receptor/hour count: {directory}")
                if set(period_hours) != {f"{hours:08d}"}:
                    raise ValueError(f"Wrong native PERIOD hour counter: {directory}")
                unique_hours = list(dict.fromkeys(timestamps))
                if len(unique_hours) != hours or any(timestamps.count(key) != count for key in unique_hours):
                    raise ValueError(f"Unexpected hourly labels: {directory}")
                blocks = hourly.reshape(hours, count, 6)
                if not np.array_equal(blocks, np.repeat(blocks[:1], hours, axis=0)):
                    raise ValueError(f"Native hourly fields are not time invariant: {directory}")
                if not np.array_equal(period[:, [0, 1, 3, 4, 5]], blocks[0][:, [0, 1, 3, 4, 5]]):
                    raise ValueError(f"Hourly/PERIOD receptor metadata differ: {directory}")
                if reference_coordinates is None:
                    reference_coordinates = period[:, :2]
                elif not np.array_equal(reference_coordinates, period[:, :2]):
                    raise ValueError(f"Cross-scenario receptor coordinates differ: {directory}")
                expected = blocks[:, :, 2].mean(axis=0) if metric == "concentration" else blocks[:, :, 2].sum(axis=0)
                if not np.allclose(period[:, 2], expected, rtol=1e-5, atol=1e-30):
                    raise ValueError(f"Native PERIOD mean/sum identity failed: {directory}")
                positive = expected > 0
                relative_error = float(np.max(np.abs(period[positive, 2] - expected[positive]) / expected[positive])) if positive.any() else 0.0
                if metric == "wet_deposition":
                    if case["precipitation_mm_h"] == 0 and np.any(hourly[:, 2] != 0):
                        raise ValueError(f"Nonzero wet deposition in no-rain control: {directory}")
                    if case["precipitation_mm_h"] > 0 and not np.any(hourly[:, 2] > 0):
                        raise ValueError(f"No wet deposition under prescribed rain: {directory}")
                summary = (directory / "aermod.sum").read_text()
                counts = {}
                for key, text in (("processed", "Hours Were Processed"), ("calm", "Calm Hours Identified"),
                                  ("missing", "Missing Hours Identified")):
                    pattern = r"A Total of\s+(\d+)\s+" + r"\s+".join(text.split())
                    match = re.search(pattern, summary, re.I)
                    if not match:
                        raise ValueError(f"Missing authoritative {key} counter: {directory}")
                    counts[key] = int(match.group(1))
                if counts != {"processed": hours, "calm": 0, "missing": 0}:
                    raise ValueError(f"Model skipped a controlled hour: {directory}: {counts}")
                execution = json.loads(Path(verification["execution_record"]["path"]).read_text())
                audit = execution.get("audit", {})
                warnings = audit.get("diagnostic_warning_codes", {})
                expected_warnings = {"MXW496": 1} if case["precipitation_mm_h"] == 0 else {}
                if warnings != expected_warnings:
                    raise ValueError(f"Unexpected native warning: {directory}: {warnings}")
                report["case_metrics"][f"{case['name']}/{metric}"] = {
                    "status": "passed", "hour_statistics": counts,
                    "hourly_rows": len(hourly), "period_rows": len(period),
                    "all_hourly_fields_bit_identical": True,
                    "reviewed_expected_warning_codes": warnings,
                    "warning_interpretation": ("MXW496 is expected because the no-rain control intentionally has zero total precipitation while wet-depletion physics remains enabled" if warnings else "No warnings"),
                    "period_operator": "mean" if metric == "concentration" else "sum",
                    "maximum_relative_period_identity_error": relative_error,
                    "rounding_tolerance": "1e-5relative allows independent native E13.6 rounding",
                    "period_minimum": float(period[:, 2].min()), "period_maximum": float(period[:, 2].max()),
                    "hourly_minimum": float(hourly[:, 2].min()), "hourly_maximum": float(hourly[:, 2].max()),
                    "hourly_nonzero_receptors_per_hour": int(np.count_nonzero(blocks[0, :, 2])),
                    "native_hourly": {"path": str(hourly_file), "sha256": digest(hourly_file)},
                    "native_period": {"path": str(period_file), "sha256": digest(period_file)},
                    "verified_native_execution": verification,
                }
        report["status"] = "passed"
        report["total_native_jobs"] = len(report["case_metrics"])
        report["total_hourly_metric_rows"] = len(report["case_metrics"]) * hours * count
        report["total_reviewed_expected_warnings"] = sum(sum(item["reviewed_expected_warning_codes"].values()) for item in report["case_metrics"].values())
        report["limitations"] = [
            "Controlled synthetic weather and source assumptions are not environmental observations.",
            "Wind variation includes physically associated derived friction velocity and heat flux, explicitly documented.",
            "Native numerical identities demonstrate stationarity and units; they do not validate environmental AMP predictions.",
        ]
    except (OSError, ValueError, KeyError) as error:
        report["status"] = "failed"
        report["error"] = str(error)
        record.write_text(json.dumps(report, indent=2, allow_nan=False) + "\n")
        raise
    record.write_text(json.dumps(report, indent=2, allow_nan=False) + "\n")
    print(json.dumps({key: report[key] for key in ("status", "total_native_jobs", "expected_receptors", "expected_hours_per_case", "total_hourly_metric_rows")}, indent=2))


if __name__ == "__main__":
    main()
