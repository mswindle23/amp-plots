#!/usr/bin/env python3
"""Observed-weather context and descriptive conditional AERMOD diagnostics.

Run after the diagnostic_d10_r1050 hourly model jobs::
    python clemson_amp/scripts/weather_figures.py --project clemson_amp

One receptor is selected at each distance per hour: the closest cardinal bearing
to the observed downwind direction. This coarse four-direction diagnostic is not
a resolved plume centreline or a mass integral. Raw precipitation coverage is
required; unreported precipitation is never classified as observed dry weather.
"""
from __future__ import annotations

import argparse
import csv
import json
import math
from pathlib import Path
import re
import sys
from datetime import datetime, timezone

from poster_figures import digest, save_figure
from result_provenance import verify_model_result
import matplotlib.pyplot as plt
import numpy as np


METRICS = {
    "concentration": ("Concentration", r"$\mu$g m$^{-3}$"),
    "dry_deposition": ("Dry deposition flux", r"g m$^{-2}$ h$^{-1}$"),
    "wet_deposition": ("Wet deposition flux", r"g m$^{-2}$ h$^{-1}$"),
}
KNOWN_PRECIP = {"observed_zero", "observed_trace", "observed_wet"}
DISTANCES_M = np.array([500., 1000., 5000., 10000.])


def time_key(year, month, day, hour):
    year, month, day, hour = map(int, (year, month, day, hour))
    if year < 100:
        year += 2000 if year < 70 else 1900
    datetime(year, month, day)  # Validate the calendar date; retain HE24 notation.
    if not 1 <= hour <= 24:
        raise ValueError("Expected local-standard hour-ending 01..24")
    return year * 1000000 + month * 10000 + day * 100 + hour


def parse_date(value):
    value = str(int(value))
    if len(value) == 8:
        value = "20" + value if int(value[:2]) < 70 else "19" + value
    if len(value) != 10:
        raise ValueError(f"Unrecognized hourly AERMOD date {value}")
    return time_key(value[:4], value[4:6], value[6:8], value[8:])


def read_surface(path):
    result, calm, missing = {}, 0, 0
    for line_number, line in enumerate(path.read_text().splitlines(), 1):
        fields = line.split()
        if not fields or not re.fullmatch(r"\d{2,4}", fields[0]):
            continue
        if len(fields) < 25:
            raise ValueError(f"{path}:{line_number}: incomplete .sfc deposition record")
        key = time_key(fields[0], fields[1], fields[2], fields[4])
        if key in result:
            raise ValueError(f"{path}: duplicate hour {key}")
        numbers = np.array([float(value) for value in fields[:25]])
        if not np.all(np.isfinite(numbers)):
            raise ValueError(f"{path}:{line_number}: nonfinite meteorology")
        wind, direction, length, ustar = numbers[[15, 16, 11, 6]]
        # Mirrors the relevant AERMOD CHKMSG criteria. The actual model's
        # presence of an hourly record supplies the final additional filter.
        missing_met = (
            wind < 0 or wind >= 90 or direction <= -9 or direction > 900
            or numbers[18] <= 0 or numbers[18] > 900 or length < -99990
            or numbers[10] < 0 or numbers[10] > 90000
            or ustar < 0 or ustar >= 9
            or (length < 0 and (numbers[9] < 0 or numbers[9] > 90000 or numbers[7] < 0))
        )
        usable = not missing_met and wind > 0 and 0 <= direction <= 360 and length != 0
        calm += int(wind == 0)
        missing += int(missing_met)
        result[key] = {"key": key, "month": int(fields[1]), "wind_m_s": wind,
                       "wind_from_degrees": direction, "obukhov_length_m": length,
                       "precipitation_mm_hr": numbers[21], "precip_code": int(numbers[20]),
                       "usable": bool(usable)}
    if not result:
        raise ValueError(f"{path}: no surface meteorology")
    return result, {"hours": len(result), "calm_hours": calm, "surface_rows_failing_numeric_qa_including_calm": missing,
                    "surface_noncalm_qa_candidate_hours": sum(row["usable"] for row in result.values()),
                    "caveat": "Surface-only screening does not establish model-valid hours; profile checks can reject additional hours."}


def read_precipitation(path):
    result = {}
    with path.open(newline="") as stream:
        for row in csv.DictReader(stream):
            year, month, day = row["date_lst"].split("-")
            key = time_key(year, month, day, row["hour_ending_lst"])
            if key in result:
                raise ValueError(f"{path}: duplicate precipitation hour {key}")
            result[key] = row["status"]
    return result


def read_hourly(path, metric):
    values, header_lines = {}, []
    for number, line in enumerate(path.read_text(encoding="ascii").splitlines(), 1):
        if line.lstrip().startswith("*"):
            header_lines.append(line)
            continue
        if not line.strip():
            continue
        fields = line.split()
        if len(fields) < 9 or fields[6] not in {"1-HR", "1", "01", "01-HR"} or fields[7] != "ALL":
            raise ValueError(f"{path}:{number}: expected single-result 1-HR POSTFILE for ALL")
        key = parse_date(fields[8])
        x, y, value = [float(field.replace("D", "E")) for field in fields[:3]]
        if not all(math.isfinite(v) for v in (x, y, value)) or value < 0:
            raise ValueError(f"{path}:{number}: invalid hourly receptor result")
        coordinate = (x, y)
        hour = values.setdefault(key, {})
        if coordinate in hour:
            raise ValueError(f"{path}:{number}: duplicate hour/receptor")
        hour[coordinate] = value
    header = "\n".join(header_lines)
    if not re.search(r"\*\s*AERMOD\s*\(", header) or not re.search(r"POST.*FILE", header):
        raise ValueError(f"{path}: authentic AERMOD POSTFILE header required")
    expected = {"concentration": "CONC", "dry_deposition": "DRY", "wet_deposition": "WET"}[metric]
    columns = next((line.split("ZELEV")[0] for line in header_lines if "ZELEV" in line), "")
    if expected not in columns:
        raise ValueError(f"{path}: unexpected metric header")
    if not values:
        raise ValueError(f"{path}: no hourly records")
    first = set(next(iter(values.values())))
    if len(first) != 16 or any(set(hour) != first for hour in values.values()):
        raise ValueError(f"{path}: diagnostic must have the same 16 receptors at every recorded hour")
    return values, {"path": str(path), "sha256": digest(path), "hours": len(values), "receptors_per_hour": 16}


def model_invalid_hours(directory, postfile_hours):
    """Read AERMOD's authoritative calm/missing flags, never infer from zeros.

    Native POSTFILE contains zero-valued records even for skipped hours. Error
    messages may include dates before STARTEND, so intersect with modeled dates
    before comparing the summary's processed/calm/missing counters.
    """
    errors_path, summary_path = directory / "errors.out", directory / "aermod.sum"
    calm, missing = set(), set()
    for line in errors_path.read_text().splitlines():
        match = re.search(r"\bMX\s+I(440|460)\b.*\b(\d{10})\s*$", line)
        if match:
            target = calm if match.group(1) == "440" else missing
            target.add(parse_date(match.group(2)))
    calm.intersection_update(postfile_hours)
    missing.intersection_update(postfile_hours)
    summary = summary_path.read_text()
    expected = {}
    for key, pattern in {
        "processed": r"A Total of\s+(\d+)\s+Hours Were Processed",
        "calm": r"A Total of\s+(\d+)\s+Calm Hours Identified",
        "missing": r"A Total of\s+(\d+)\s+Missing Hours Identified",
    }.items():
        matches = re.findall(pattern, summary, flags=re.IGNORECASE)
        if len(matches) != 1:
            raise ValueError(f"{summary_path}: expected one authoritative {key}-hour counter")
        expected[key] = int(matches[0])
    actual = {"processed": len(postfile_hours), "calm": len(calm), "missing": len(missing)}
    if expected != actual:
        raise ValueError(f"Model-hour flags disagree with summary: {actual}, expected {expected}")
    return calm | missing, {
        "source": "AERMOD errors.out I440 calm / I460 missing, checked against aermod.sum",
        "processed_hours": len(postfile_hours), "calm_hours": len(calm), "missing_hours": len(missing),
        "valid_modeled_hours": len(postfile_hours - calm - missing),
        "calm_hour_ending_lst": sorted(calm), "missing_hour_ending_lst": sorted(missing),
        "error_messages": {"path": str(errors_path), "sha256": digest(errors_path)},
        "summary": {"path": str(summary_path), "sha256": digest(summary_path)},
    }


def precipitation_class(surface, status):
    """Keep observed trace separate and exclude raw/processed contradictions."""
    amount = surface["precipitation_mm_hr"]
    if status not in KNOWN_PRECIP or not 0 <= amount <= 900 or surface["precip_code"] == 99:
        return None
    if status == "observed_wet" and amount > 0:
        return "0 < P ≤ 1" if amount <= 1 else "P > 1"
    if status == "observed_trace" and amount == 0:
        return "Trace"
    if status == "observed_zero" and amount == 0:
        return "Reported zero"
    return None  # Raw candidate and processed category disagree: unresolved merge.


def weather_context(surface, precip, output, artifacts, invalid_hours=None):
    rows = [row for row in surface.values() if row["usable"] and (invalid_hours is None or row["key"] not in invalid_hours)]
    if not rows:
        raise ValueError("No eligible noncalm meteorological hours")
    fig = plt.figure(figsize=(11.1, 3.8))
    ax_wind = fig.add_subplot(131, projection="polar")
    ax_stability = fig.add_subplot(132)
    ax_rain = fig.add_subplot(133)
    directions = np.array([row["wind_from_degrees"] for row in rows])
    speed = np.array([row["wind_m_s"] for row in rows])
    centers = np.arange(0, 360, 22.5)
    sector = (np.floor((directions + 11.25) / 22.5).astype(int) % 16)
    base = np.zeros(16)
    for selected, label, color in ((speed < 2, "< 2 m s⁻¹", "#56B4E9"),
                                    ((speed >= 2) & (speed < 5), "2–<5 m s⁻¹", "#0072B2"),
                                    (speed >= 5, "≥5 m s⁻¹", "#D55E00")):
        counts = np.bincount(sector[selected], minlength=16)
        fractions = counts / len(rows) * 100
        ax_wind.bar(np.deg2rad(centers), fractions, width=np.deg2rad(21),
                    bottom=base, color=color, label=label, edgecolor="white", linewidth=0.3)
        base += fractions
    ax_wind.set_theta_zero_location("N")
    ax_wind.set_theta_direction(-1)
    ax_wind.set_title("Observed wind FROM direction", pad=17, fontsize=10)
    ax_wind.set_xticks(np.deg2rad(np.arange(0, 360, 45)), ["N", "NE", "E", "SE", "S", "SW", "W", "NW"], fontsize=8)
    ax_wind.tick_params(axis="y", labelsize=7)
    ax_wind.legend(fontsize=7, frameon=False, loc="lower center", bbox_to_anchor=(0.5, -0.22), ncol=1)
    stable = int(sum(row["obukhov_length_m"] > 0 for row in rows))
    unstable = int(sum(row["obukhov_length_m"] < 0 for row in rows))
    ax_stability.bar(["L < 0\nUnstable", "L > 0\nStable"], [unstable, stable], color=["#D55E00", "#0072B2"])
    ax_stability.set_title("Surface QA candidates" if invalid_hours is None else "Model-valid noncalm meteorology", fontsize=10)
    ax_stability.set_ylabel("Hours")
    for i, count in enumerate([unstable, stable]):
        ax_stability.text(i, count, str(count), ha="center", va="bottom", fontsize=8)
    rain, unknown = [], []
    for month in range(1, 13):
        month_rows = [row for row in surface.values() if row["month"] == month]
        known = [row for row in month_rows if precipitation_class(row, precip.get(row["key"])) is not None]
        rain.append(float(sum(row["precipitation_mm_hr"] for row in known)))
        unknown.append(len(month_rows) - len(known))
    ax_rain.bar(np.arange(1, 13), rain, color="#009E73")
    ax_rain.set_title("Processed precipitation, known hours", fontsize=10)
    ax_rain.set_xlabel("Month (2023)")
    ax_rain.set_ylabel("Sum of hourly precipitation (mm)")
    ax_rain.set_xticks([1, 3, 5, 7, 9, 11])
    ax_rain.text(0.02, 0.96, f"{sum(unknown)} unknown/discordant hours excluded", transform=ax_rain.transAxes, va="top", fontsize=7)
    fig.suptitle("Clemson meteorological context — observed surface data / AERMET processing", fontsize=12)
    fig.text(0.06, 0.015,
             ("Wind uses noncalm surface QA candidates; profile checks may reject further hours. " if invalid_hours is None
              else "Wind uses model-valid noncalm hours. ") + "Stability uses the sign of Monin–Obukhov length L.\n"
             "Precipitation coverage audited against raw one-hour reports; trace retained as zero resolved depth, never substituted for missing rainfall.", fontsize=7.5)
    fig.subplots_adjust(left=0.06, right=0.98, wspace=0.47, top=0.79, bottom=0.23)
    save_figure(fig, output, "meteorological_context", artifacts)
    return {"wind_rose_denominator_hours": len(rows), "stable_hours": stable, "unstable_hours": unstable,
            "monthly_resolved_precipitation_mm": rain, "monthly_unknown_or_discordant_hours": unknown}


def aggregate(values):
    array = np.asarray(values)
    if not len(array):
        return {"n": 0, "mean": None, "median": None}
    return {"n": len(array), "mean": float(array.mean()), "median": float(np.median(array))}


def conditional_figures(scenario, surface, precip, outputs, output, artifacts, invalid_hours):
    center = scenario["center"]
    first = next(iter(outputs["concentration"].values()))
    coordinates = np.array(list(first), dtype=float)
    east = coordinates[:, 0] - center["easting_m"]
    north = coordinates[:, 1] - center["northing_m"]
    distances = np.hypot(east, north)
    bearings = np.rad2deg(np.arctan2(east, north)) % 360
    radial_indices = []
    for distance in DISTANCES_M:
        indices = np.flatnonzero(np.abs(distances - distance) < 1)
        if len(indices) != 4:
            raise ValueError(f"Expected four cardinal diagnostic receptors at {distance:g} m")
        radial_indices.append(indices)
    rows = []
    for key, weather in sorted(surface.items()):
        if not weather["usable"] or key not in outputs["concentration"] or key in invalid_hours:
            continue
        downwind = (weather["wind_from_degrees"] + 180) % 360
        differences = np.abs((bearings - downwind + 180) % 360 - 180)
        selected = [indices[np.argmin(differences[indices])] for indices in radial_indices]
        if any(differences[index] > 45.01 for index in selected):
            raise ValueError("Diagnostic receptors do not support nearest-cardinal selection")
        row = dict(weather)
        row["wind_bin"] = "<2" if weather["wind_m_s"] < 2 else "2–<5" if weather["wind_m_s"] < 5 else "≥5"
        row["stability"] = "Unstable (L<0)" if weather["obukhov_length_m"] < 0 else "Stable (L>0)"
        row["precipitation_class"] = precipitation_class(weather, precip.get(key))
        for metric in METRICS:
            row[metric] = [outputs[metric][key][tuple(coordinates[index])] for index in selected]
        rows.append(row)
    if not rows:
        raise ValueError("No matched, usable noncalm model/weather hours")
    stats = {"matched_usable_hours": len(rows), "model_flagged_calm_or_missing_hours_excluded": len(invalid_hours),
             "max_cardinal_misalignment_degrees": 45,
             "known_precipitation_hours": sum(row["precipitation_class"] is not None for row in rows),
             "excluded_precipitation_hours": sum(row["precipitation_class"] is None for row in rows),
             "bins": {}}
    fig, axes = plt.subplots(1, 3, figsize=(11.4, 3.8))
    palette = ["#56B4E9", "#0072B2", "#D55E00"]
    for ax, (metric, (label, unit)) in zip(axes, METRICS.items()):
        has_positive = False
        for wind_bin, color in zip(["<2", "2–<5", "≥5"], palette):
            selected = [row for row in rows if row["wind_bin"] == wind_bin]
            grouped = [aggregate([row[metric][index] for row in selected]) for index in range(4)]
            stats["bins"][f"wind/{metric}/{wind_bin}"] = grouped
            means = [group["mean"] if group["mean"] is not None else np.nan for group in grouped]
            means = np.asarray(means, dtype=float)
            has_positive = has_positive or bool(np.any(means > 0))
            ax.plot(DISTANCES_M / 1000, np.where(means > 0, means, np.nan), "o-", color=color, ms=4,
                    label=f"{wind_bin} m s⁻¹ (n={len(selected)})")
        ax.set_xscale("log")
        ax.set_xlabel("Receptor distance (km)")
        ax.set_xticks([0.5, 1, 5, 10], ["0.5", "1", "5", "10"])
        ax.set_ylabel(f"{label} ({unit})", fontsize=9)
        if has_positive:
            ax.set_yscale("log")
        else:
            ax.set_ylim(0, 1)
            ax.text(0.5, 0.5, "No positive printed means", transform=ax.transAxes, ha="center")
        ax.grid(alpha=0.18)
    axes[0].legend(fontsize=7, frameon=False)
    fig.suptitle("Descriptive wind-speed comparison — 10 µm, 1.05 g cm⁻³ spherical surrogate", fontsize=12)
    fig.text(0.07, 0.025,
             "Hourly nearest downwind cardinal receptor (one of N/E/S/W; ≤45° misalignment); arithmetic means by wind speed, positive means on log axes.\n"
             "Weather groups differ in stability, rainfall and direction; associations are not causal wind experiments or a resolved transport distance.", fontsize=7.5)
    fig.subplots_adjust(left=0.07, right=0.98, top=0.85, bottom=0.25, wspace=0.34)
    save_figure(fig, output, "wind_conditioned_receptor_profiles", artifacts)

    fig, axes = plt.subplots(1, 3, figsize=(11.4, 4.0))
    stability_labels = ["Unstable (L<0)", "Stable (L>0)"]
    wind_bins = ["<2", "2–<5", "≥5"]
    for offset, stability, color in zip([-0.17, 0.17], stability_labels, ["#D55E00", "#0072B2"]):
        means, counts = [], []
        for wind_bin in wind_bins:
            group = aggregate([row["concentration"][1] for row in rows if row["wind_bin"] == wind_bin and row["stability"] == stability])
            stats["bins"][f"stability/concentration/{stability}/{wind_bin}"] = group
            means.append(group["mean"] or 0)
            counts.append(group["n"])
        bars = axes[0].bar(np.arange(3) + offset, means, width=0.32, color=color, label=stability)
        for bar, count in zip(bars, counts):
            axes[0].annotate(f"n={count}", (bar.get_x() + bar.get_width()/2, bar.get_height()),
                             xytext=(0, 3), textcoords="offset points", ha="center", fontsize=6.5)
    axes[0].set_xticks(np.arange(3), [f"{label} m s⁻¹" for label in wind_bins], fontsize=8)
    axes[0].set_ylabel(r"Mean concentration ($\mu$g m$^{-3}$)")
    axes[0].legend(fontsize=7, frameon=False)
    categories = ["Reported zero", "Trace", "0 < P ≤ 1", "P > 1"]
    for ax, metric in zip(axes[1:], ["dry_deposition", "wet_deposition"]):
        grouped = [aggregate([row[metric][1] for row in rows if row["precipitation_class"] == category]) for category in categories]
        for category, group in zip(categories, grouped):
            stats["bins"][f"precipitation/{metric}/{category}"] = group
        bars = ax.bar(np.arange(4), [group["mean"] or 0 for group in grouped], color="#009E73")
        for bar, group in zip(bars, grouped):
            ax.annotate(f"n={group['n']}", (bar.get_x() + bar.get_width()/2, bar.get_height()),
                        xytext=(0, 3), textcoords="offset points", ha="center", fontsize=6.5)
        ax.set_xticks(np.arange(4), ["Reported\nzero", "Trace", "0<P≤1", "P>1"], fontsize=8)
        ax.set_xlabel("Precipitation P (mm h⁻¹)")
        ax.set_ylabel(f"Mean {METRICS[metric][0].lower()} ({METRICS[metric][1]})", fontsize=9)
    for ax in axes:
        ax.ticklabel_format(axis="y", style="sci", scilimits=(-2, 2))
        ax.set_ylim(bottom=0)
    fig.suptitle("Observed weather groups at the nearest downwind 1 km cardinal receptor", fontsize=12)
    fig.text(0.07, 0.025,
             "10 µm, 1.05 g cm⁻³; normalized 1 g s⁻¹ hypothetical source. Bars are means, not causal effects; counts are usable modeled hours.\n"
             "Unknown or raw/processed-discordant precipitation excluded from rainfall groups. Trace remains separate; zero model results remain in means.", fontsize=7.5)
    fig.subplots_adjust(left=0.07, right=0.98, top=0.85, bottom=0.26, wspace=0.39)
    save_figure(fig, output, "stability_precipitation_comparison", artifacts)
    table_path = output / "weather_conditioned_hourly_diagnostics.csv"
    fields = ["hour_ending_lst", "wind_m_s", "wind_from_degrees", "obukhov_length_m", "precipitation_mm_hr", "precipitation_class", "distance_m", *METRICS]
    with table_path.open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            for index, distance in enumerate(DISTANCES_M):
                record = {key: row[key] for key in fields if key in row and key not in METRICS}
                record.update(hour_ending_lst=row["key"], distance_m=distance,
                              **{metric: row[metric][index] for metric in METRICS})
                writer.writerow(record)
    artifacts.append({"path": str(table_path), "sha256": digest(table_path)})
    return stats


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--project", type=Path, default=Path("clemson_amp"))
    parser.add_argument("--context-only", action="store_true", help="Only observed-weather context; no modeled conditional results")
    args = parser.parse_args(argv)
    project = args.project.resolve()
    output = project / "figures"
    output.mkdir(exist_ok=True)
    paths = {"scenario": project / "scenario.json", "surface": project / "aermet" / "clemson.sfc",
             "raw_precipitation_coverage": project / "data" / "met" / "hourly_precipitation_coverage.csv"}
    artifacts = []
    provenance = {"created_utc": datetime.now(timezone.utc).isoformat(), "status": "in_progress",
                  "mode": "context-only" if args.context_only else "weather context and descriptive modeled conditionals",
                  "script": {"path": str(Path(__file__).resolve()), "sha256": digest(Path(__file__))},
                  "result_verifier": {"path": str(Path(__file__).with_name("result_provenance.py")),
                                      "sha256": digest(Path(__file__).with_name("result_provenance.py"))},
                  "artifacts": artifacts, "inputs": {},
                  "limitations": [
                      "Nearest downwind cardinal receptor can differ from actual downwind by up to 45 degrees; this is not a plume-centreline calculation.",
                      "Observed weather groups differ in other conditions; comparisons are descriptive and do not isolate causal wind, stability, or rainfall effects.",
                      "Hypothetical equal-mass source and spherical surrogate; no measured AMP concentrations or emissions.",
                      "Raw precipitation coverage is a candidate-record audit, not an exact recreation of AERMET duplicate merging. Unknown or discordant categories are excluded.",
                      "Hourly dry/wet output is mass per area for one hour, numerically the one-hour mean flux in g/m²/hr; PERIOD deposition outputs elsewhere are accumulated g/m².",
                  ]}
    record = output / ("weather_context_provenance.json" if args.context_only else "weather_figures_provenance.json")
    try:
        for name, path in paths.items():
            provenance["inputs"][name] = {"path": str(path), "sha256": digest(path)}
        scenario = json.loads(paths["scenario"].read_text())
        surface, provenance["surface_audit"] = read_surface(paths["surface"])
        precip = read_precipitation(paths["raw_precipitation_coverage"])
        invalid_hours = None
        if not args.context_only:
            hourly = {}
            invalid_by_metric = {}
            for metric in METRICS:
                path = project / "aermod" / "diagnostic_d10_r1050" / metric / "hourly.plt"
                execution_provenance = verify_model_result(project, path)
                hourly[metric], provenance["inputs"][metric] = read_hourly(path, metric)
                provenance["inputs"][metric]["verified_native_execution"] = execution_provenance
                invalid_by_metric[metric], provenance["inputs"][metric]["model_hour_audit"] = model_invalid_hours(path.parent, set(hourly[metric]))
            reference = hourly["concentration"]
            for metric, values in hourly.items():
                if set(reference) != set(values) or any(set(reference[key]) != set(values[key]) for key in reference):
                    raise ValueError(f"{metric}: hourly dates/receptors do not match across metrics")
                if invalid_by_metric[metric] != invalid_by_metric["concentration"]:
                    raise ValueError(f"{metric}: model-invalid hours differ across metrics")
            invalid_hours = set.union(*invalid_by_metric.values())
            provenance["conditional_statistics"] = conditional_figures(scenario, surface, precip, hourly, output, artifacts, invalid_hours)
        provenance["weather_context"] = weather_context(surface, precip, output, artifacts, invalid_hours)
        provenance["status"] = "complete"
    except (OSError, ValueError, KeyError) as exc:
        provenance.update(status="failed; modeled conditional figures not validated", error=str(exc))
        record.write_text(json.dumps(provenance, indent=2, allow_nan=False) + "\n")
        print(exc, file=sys.stderr)
        return 1
    record.write_text(json.dumps(provenance, indent=2, allow_nan=False) + "\n")
    print(f"Saved {len(artifacts)} artifacts and {record}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
