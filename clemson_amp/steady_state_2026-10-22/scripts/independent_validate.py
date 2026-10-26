#!/usr/bin/env python3
"""Independently audit native fields and physical controls after steady runs.

This audit reads the model's ASCII products directly. It neither imports the
input generator nor uses plotting/exported summary tables as its reference.
"""
from __future__ import annotations

import argparse
from datetime import date
import hashlib
import json
import math
from pathlib import Path
import re
import sys

import numpy as np


METRICS = ("concentration", "dry_deposition", "wet_deposition")


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def native(path: Path, hourly: bool) -> np.ndarray:
    data = np.loadtxt(path, comments="*", usecols=(0, 1, 2, 8), ndmin=2)
    if not np.isfinite(data).all() or np.any(data[:, 2] < 0):
        raise ValueError(f"Invalid native numeric values: {path}")
    if hourly:
        dates, counts = np.unique(data[:, 3], return_counts=True)
        if len(dates) != 24 or len(set(counts)) != 1:
            raise ValueError(f"Incomplete hourly product: {path}")
        data = data.reshape(24, int(counts[0]), 4)
        if not all(np.array_equal(data[i, :, :2], data[0, :, :2]) for i in range(1, 24)):
            raise ValueError(f"Hourly receptor coordinates differ: {path}")
        if not all(np.unique(data[i, :, 3]).size == 1 for i in range(24)):
            raise ValueError(f"Hourly chunks contain mixed timestamps: {path}")
    return data


def terrain_rows(path: Path) -> dict:
    rows = {}
    for line in path.read_text().splitlines():
        fields = line.split()
        if fields[:1] == ["RE"]:
            fields = fields[1:]
        if fields[:1] != ["DISCCART"]:
            continue
        row = tuple(map(float, fields[1:5]))
        if row[:2] in rows or not all(math.isfinite(value) for value in row):
            raise ValueError(f"Duplicate or invalid terrain receptor: {path}")
        rows[row[:2]] = row[2:]
    return rows


def verify_terrain(project: Path) -> dict:
    refined = project / "aermap_refined"
    audit_path = refined / "aermap_validation.json"
    audit = json.loads(audit_path.read_text())
    if audit.get("status") != "passed":
        raise ValueError("Refined AERMAP audit has not passed")
    checked = {}

    def verify_records(value):
        if isinstance(value, dict):
            if isinstance(value.get("path"), str) and "sha256" in value:
                path = Path(value["path"])
                path = path if path.is_absolute() else project / path
                if str(path) not in checked:
                    checked[str(path)] = digest(path)
                actual = checked[str(path)]
                if actual != value["sha256"]:
                    raise ValueError(f"AERMAP provenance artifact changed: {path}")
            for child in value.values():
                verify_records(child)
        elif isinstance(value, list):
            for child in value:
                verify_records(child)

    verify_records(audit)
    merged_path = project / "aermap" / "aermap.rec"
    merged = terrain_rows(merged_path)
    shards, union = [], {}
    for directory in sorted((refined / "chunks").glob("chunk_*")):
        if not directory.is_dir():
            continue
        report = directory / "aermap.out"
        if "AERMAP Finishes Successfully" not in report.read_text():
            raise ValueError(f"AERMAP shard lacks native completion: {report}")
        shard = terrain_rows(directory / "aermap.rec")
        if not shard or set(union).intersection(shard):
            raise ValueError(f"Empty or overlapping AERMAP receptor shard: {directory}")
        union.update(shard)
        shards.append({"directory": str(directory), "receptors": len(shard),
                       "native_output": {"path": str(directory / "aermap.rec"), "sha256": digest(directory / "aermap.rec")},
                       "native_report": {"path": str(report), "sha256": digest(report)}})
    if len(shards) != 4 or len(merged) != 2736 or merged != union:
        raise ValueError("Merged terrain is not the exact union of four native AERMAP receptor outputs")
    original = terrain_rows(project.parent / "aermap" / "aermap.rec")
    if len(original) != 873 or not set(original).issubset(merged):
        raise ValueError("Original receptor coordinates were not retained")
    for coordinate, heights in original.items():
        if not np.allclose(heights, merged[coordinate], rtol=0, atol=0.010001):
            raise ValueError("Original terrain or critical-hill height changed")
    if not all(hill >= elevation for elevation, hill in merged.values()):
        raise ValueError("Critical-hill height is below receptor ground")
    return {"status": "passed", "merged_receptors": len(merged),
            "verified_aermap_artifact_hashes": len(checked),
            "original_receptors_retained": len(original), "new_receptors": len(merged) - len(original),
            "exact_native_shard_union": True, "shards": shards,
            "merged_native_include": {"path": str(merged_path), "sha256": digest(merged_path)},
            "refined_aermap_audit": {"path": str(audit_path), "sha256": digest(audit_path)}}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args()
    project = args.project.resolve()
    # This is the generic execution-record verifier, not a numerical reference.
    sys.path.insert(0, str(project.parent / "scripts"))
    from result_provenance import verify_model_result

    scenario_path = project / "scenario.json"
    scenario = json.loads(scenario_path.read_text())
    config = scenario["meteorology"]
    terrain_check = verify_terrain(project)
    calendar_date = date.fromisoformat(scenario["simulation_date"])
    expected_native_dates = ((calendar_date.year % 100) * 1000000 + calendar_date.month * 10000
                             + calendar_date.day * 100 + np.arange(1, 25))
    expected_receptors = sum(bool(re.match(r"\s*(?:RE\s+)?DISCCART\s", line))
                             for line in (project / "aermap" / "aermap.rec").read_text().splitlines())
    if expected_receptors <= 0:
        raise ValueError("No explicit AERMAP receptor definitions found")
    native_checks, meteorology_checks, baseline_fields = [], [], {}
    coordinate_reference = None
    constant_surface_reference = None
    # These are the only physical surface fields allowed to change between
    # cases: heat flux, friction velocity, mean wind, precipitation code/rate.
    surface_varying_indices = {5, 6, 15, 20, 21}
    surface_constant_indices = [index for index in range(5, 25)
                                if index not in surface_varying_indices]
    for case in scenario["particle_cases"]:
        met_path = project / case["surface_file"]
        met = np.loadtxt(met_path, skiprows=1, usecols=tuple(range(25)), ndmin=2)
        if met.shape != (24, 25):
            raise ValueError(f"Expected24complete surface records: {met_path}")
        expected_calendar = [calendar_date.year, calendar_date.month, calendar_date.day,
                             calendar_date.timetuple().tm_yday]
        if not np.all(met[:, :4] == expected_calendar) or not np.array_equal(met[:, 4], np.arange(1, 25)):
            raise ValueError(f"Surface calendar does not match the experiment: {met_path}")
        if not np.all(met[:, 5:] == met[0, 5:]):
            raise ValueError(f"Surface conditions vary over time: {met_path}")
        constant = met[0, surface_constant_indices]
        if constant_surface_reference is None:
            constant_surface_reference = constant
        elif not np.array_equal(constant_surface_reference, constant):
            raise ValueError(f"An undeclared meteorological control changes: {met_path}")
        reference_wind = case["wind_speed_m_s"]
        if met[0, 15] != reference_wind or met[0, 21] != case["precipitation_mm_h"]:
            raise ValueError(f"Surface wind/rain does not match the case: {met_path}")
        if met[0, 20] != (11 if case["precipitation_mm_h"] else 0):
            raise ValueError(f"Unexpected synthetic precipitation code: {met_path}")
        expected_ustar = config["von_karman_constant"] * reference_wind / (
            math.log(config["wind_reference_height_m"] / config["roughness_length_m"])
            + 5 * (config["wind_reference_height_m"] - config["roughness_length_m"])
            / config["monin_obukhov_length_m"])
        expected_heat = -(config["air_density_kg_m3"] * config["air_specific_heat_J_kg_K"]
                          * config["air_temperature_K"] * expected_ustar ** 3
                          / (config["von_karman_constant"] * config["gravity_m_s2"]
                             * config["monin_obukhov_length_m"]))
        if not math.isclose(met[0, 6], expected_ustar, rel_tol=2e-11):
            raise ValueError(f"Wind and friction velocity are inconsistent: {met_path}")
        if not math.isclose(met[0, 5], expected_heat, rel_tol=2e-11):
            raise ValueError(f"Heat flux and Monin-Obukhov length are inconsistent: {met_path}")
        pfl_path = project / case["profile_file"]
        pfl = np.loadtxt(pfl_path, ndmin=2)
        if pfl.shape != (24, 11) or not np.all(pfl[:, 4:] == pfl[0, 4:]):
            raise ValueError(f"Profile varies over time or is incomplete: {pfl_path}")
        if not np.all(pfl[:, 7] == reference_wind) or not np.all(pfl[:, 6] == 270):
            raise ValueError(f"Profile wind mismatches the controlled case: {pfl_path}")
        meteorology_checks.append({
            "case": case["name"], "hours": 24,
            "surface_time_invariant": True, "profile_time_invariant": True,
            "wind_m_s": reference_wind, "precipitation_mm_h": case["precipitation_mm_h"],
            "friction_velocity_m_s": float(met[0, 6]),
            "sensible_heat_flux_W_m2": float(met[0, 5]),
            "neutral_limit_surface_layer_consistency": "passed",
            "surface": {"path": str(met_path), "sha256": digest(met_path)},
            "profile": {"path": str(pfl_path), "sha256": digest(pfl_path)},
        })
        baseline_fields[case["name"]] = {}
        for metric in METRICS:
            directory = project / "aermod" / case["name"] / metric
            verification = verify_model_result(project, directory / "annual.plt")
            verify_model_result(project, directory / "hourly.plt")
            deck = (directory / "aermod.inp").read_text()
            cards = {}
            for line in deck.splitlines():
                fields = line.split()
                if len(fields) >= 3 and fields[0] in {"CO", "SO", "RE", "ME", "OU"}:
                    cards[tuple(fields[:2])] = fields[2:]
            expected_area_flux = (scenario["source"]["total_emission_g_s"]
                                  / (scenario["source"]["x_length_m"] * scenario["source"]["y_length_m"]))
            source_fields = cards[("SO", "SRCPARAM")]
            if not math.isclose(float(source_fields[1]), expected_area_flux, rel_tol=2e-11):
                raise ValueError(f"Source emission flux does not match the scenario: {directory}")
            for keyword, expected in (("PARTDIAM", scenario["particle"]["diameter_um"]),
                                      ("PARTDENS", scenario["particle"]["density_g_cm3"]),
                                      ("MASSFRAX", 1.0)):
                if not math.isclose(float(cards[("SO", keyword)][1]), expected, rel_tol=2e-11):
                    raise ValueError(f"Particle {keyword} differs from the scenario: {directory}")
            if not {"DRYDPLT", "WETDPLT"}.issubset(cards[("CO", "MODELOPT")]):
                raise ValueError(f"Dry/wet plume depletion is not consistent: {directory}")
            if "OU FILEFORM EXP" not in deck:
                raise ValueError(f"Scientific-format output missing: {directory}")
            if "SO DEPOUNIT 3.6E9 GRAMS/SEC MICROGRAMS/M2" not in deck:
                raise ValueError(f"Unexpected deposition unit convention: {directory}")
            if "SO CONCUNIT 1.0E6 GRAMS/SEC MICROGRAMS/M3" not in deck:
                raise ValueError(f"Unexpected concentration unit convention: {directory}")
            period = native(directory / "annual.plt", False)
            hourly = native(directory / "hourly.plt", True)
            if len(period) != expected_receptors or hourly.shape[1] != expected_receptors:
                raise ValueError(f"Native receptor count differs from AERMAP include: {directory}")
            if not np.array_equal(np.unique(hourly[:, :, 3]), expected_native_dates):
                raise ValueError(f"Native output dates do not match the experiment: {directory}")
            if not np.array_equal(period[:, :2], hourly[0, :, :2]):
                raise ValueError(f"PERIOD and hourly coordinates differ: {directory}")
            if coordinate_reference is None:
                coordinate_reference = period[:, :2]
            elif not np.array_equal(coordinate_reference, period[:, :2]):
                raise ValueError(f"Receptor coordinates differ across cases: {directory}")
            if not np.all(hourly[:, :, 2] == hourly[0, :, 2]):
                raise ValueError(f"Native hourly field is not steady: {directory}")
            target = (hourly[:, :, 2].mean(axis=0) if metric == "concentration"
                      else hourly[:, :, 2].sum(axis=0))
            # Both ASCII representations round independently to six
            # significant decimal digits. This tolerance is for that format.
            if not np.allclose(target, period[:, 2], rtol=1.2e-5, atol=1e-300):
                raise ValueError(f"PERIOD aggregation is inconsistent: {directory}")
            nonzero = target > 0
            max_relative = (float(np.max(np.abs(target[nonzero] - period[nonzero, 2]) / target[nonzero]))
                            if np.any(nonzero) else 0.0)
            summary = (directory / "aermod.sum").read_text()
            completion = (directory / "aermod.out").read_text()
            messages = (directory / "errors.out").read_text()
            expected_warnings = [("MX", "W496")] if case["precipitation_mm_h"] == 0 else []
            actual_warnings = re.findall(r"^\s*([A-Z]{2})\s+(W\d{3})\b", messages, re.M)
            if actual_warnings != expected_warnings:
                raise ValueError(f"Unexpected warning inventory: {directory}: {actual_warnings}")
            if "AERMOD Finishes Successfully" not in completion:
                raise ValueError(f"Native AERMOD completion marker missing: {directory}")
            if not re.search(r"A Total of\s+0\s+Fatal Error Message", completion):
                raise ValueError(f"Native AERMOD fatal-error count is not zero: {directory}")
            if not re.search(r"A Total of\s+" + str(len(expected_warnings)) + r"\s+Warning Message", completion):
                raise ValueError(f"Native warning counter disagrees with messages: {directory}")
            for expected, phrase in ((24, "Hours Were Processed"), (0, "Calm Hours Identified"),
                                     (0, "Missing Hours Identified")):
                if not re.search(r"A Total of\s+" + str(expected) + r"\s+" + phrase, summary):
                    raise ValueError(f"Unexpected processed-hour counters: {directory}")
            baseline_fields[case["name"]][metric] = hourly[0, :, 2].copy()
            native_checks.append({
                "case": case["name"], "metric": metric, "receptors": len(period), "hours": 24,
                "hourly_fields_identical": True,
                "period_rule": "mean" if metric == "concentration" else "sum",
                "fatal_errors": 0, "warning_codes": [pathway + code for pathway, code in actual_warnings],
                "period_hourly_max_relative_difference": max_relative,
                "positive_receptors": int(np.count_nonzero(nonzero)),
                "hourly_positive_min": float(target[nonzero].min() / (1 if metric == "concentration" else 24)) if np.any(nonzero) else None,
                "hourly_max": float(hourly[:, :, 2].max()),
                "period_max": float(period[:, 2].max()),
                "execution_record": verification["execution_record"],
                "hourly_output": {"path": str(directory / "hourly.plt"), "sha256": digest(directory / "hourly.plt")},
                "period_output": {"path": str(directory / "annual.plt"), "sha256": digest(directory / "annual.plt")},
            })
    paired_checks = []
    for wind in sorted({case["wind_speed_m_s"] for case in scenario["particle_cases"]}):
        dry_case = next(case for case in scenario["particle_cases"] if case["wind_speed_m_s"] == wind and case["precipitation_mm_h"] == 0)
        wet_case = next(case for case in scenario["particle_cases"] if case["wind_speed_m_s"] == wind and case["precipitation_mm_h"] == 1)
        dry, wet = baseline_fields[dry_case["name"]], baseline_fields[wet_case["name"]]
        if np.any(dry["wet_deposition"] != 0):
            raise ValueError(f"No-rain case has nonzero wet deposition: {dry_case['name']}")
        for metric in ("concentration", "dry_deposition"):
            if np.any(wet[metric] > dry[metric] * (1 + 1.2e-5) + 1e-300):
                raise ValueError(f"Wet removal increased {metric}: wind{wind}")
        if not np.any(wet["wet_deposition"] > 0):
            raise ValueError(f"Rain case has no wet deposition: {wet_case['name']}")
        paired_checks.append({"wind_m_s": wind, "no_rain_wet_deposition_exact_zero": True,
                              "rain_concentration_not_greater_than_no_rain": True,
                              "rain_dry_deposition_not_greater_than_no_rain": True})
    report = {
        "status": "passed", "method": "Independent direct native ASCII calculations and physical checks; no figure/export tables used",
        "script": {"path": str(Path(__file__).resolve()), "sha256": digest(Path(__file__))},
        "scenario": {"path": str(scenario_path), "sha256": digest(scenario_path)},
        "native_jobs": len(native_checks), "cases": len(meteorology_checks),
        "receptors_per_job": len(coordinate_reference), "modeled_hours_per_case": 24,
        "hourly_metric_rows": len(native_checks) * 24 * len(coordinate_reference),
        "native_warning_total": sum(len(item["warning_codes"]) for item in native_checks),
        "terrain_check": terrain_check,
        "meteorology_checks": meteorology_checks, "native_checks": native_checks, "paired_rain_checks": paired_checks,
        "interpretation": [
            "Identical stationary forcing yields constant hourly flux, not a transient plume-arrival calculation.",
            "Deposition PERIOD is accumulated ug/m2; hourly amounts are numerically ug/m2/h for one-hour intervals.",
            "Friction velocity and tiny heat flux change consistently with wind; stability length and other stated controls stay fixed.",
            "Selected calendar year does not establish complete annual observed microplastic or meteorological coverage.",
        ],
    }
    path = project / "independent_validation.json"
    path.write_text(json.dumps(report, indent=2, allow_nan=False) + "\n")
    (project / "independent_validation.md").write_text(
        "# Independent scientific validation\n\n"
        f"Passed: {len(native_checks)} native AERMOD jobs across {len(meteorology_checks)} controlled cases. "
        f"Each case contains 24 valid modeled hours and {len(coordinate_reference):,} terrain receptors.\n\n"
        "The audit reads authentic native ASCII files directly, independently of the plotting and Excel export tables. "
        "It verifies current execution/input/output hashes; constant weather within each case; physically consistent "
        "friction velocity and tiny heat flux; common stability and other prescribed controls; exactly repeating "
        "hourly receptor fields; PERIOD mean concentration; and PERIOD summed deposition within scientific-format rounding.\n\n"
        "No fatal errors occurred. The 15 no-rain quantity runs each produce one expected MX W496 warning "
        "because wet deposition remains enabled with zero precipitation; this is the intended control. "
        "All 15 rain runs have zero warnings. No other warning codes are accepted.\n\n"
        "The merged terrain is the exact union of four successful native full-tile AERMAP runs. "
        "All 873 original receptors remain, with ground and hill heights agreeing within 0.01 m. "
        "The 1,863 additional receptors improve resolution along the eastward plume.\n\n"
        "Every no-rain case has exactly zero wet deposition. At the same wind speed, introducing rain does not "
        "increase concentration or dry deposition because wet plume depletion is also active. "
        "All three output quantities use the same particle, source, terrain and meteorology per case.\n\n"
        "Hourly deposition is an amount in µg/m² over one hour, numerically equal to mean flux in µg/m²/h. "
        "PERIOD deposition is accumulated µg/m² across 24 hours; concentration is a mean in µg/m³. "
        "Identical stationary forcing gives constant hourly flux and linearly increasing accumulation; "
        "this does not model plume startup or advancing-puff travel time.\n\n"
        "The common year is a calendar/reference label. Available regional observations do not establish a complete "
        "annual Clemson microplastic inventory. Source emissions and synthetic weather remain explicit scenario assumptions. "
        "Friction velocity and heat flux change with reference wind across speeds; the experiment is not described "
        "as holding every turbulence quantity fixed while changing wind.\n\n"
        "Detailed per-case numeric checks and exact native file hashes are in `independent_validation.json`.\n")
    print(json.dumps({key: report[key] for key in ("status", "native_jobs", "cases", "receptors_per_job", "modeled_hours_per_case", "hourly_metric_rows")}, indent=2))


if __name__ == "__main__":
    main()
