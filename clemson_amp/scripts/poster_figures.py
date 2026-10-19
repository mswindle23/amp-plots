#!/usr/bin/env python3
"""Render poster figures from actual single-metric AERMOD PERIOD PLOTFILEs.

Example (from the repository root)::

    python clemson_amp/scripts/poster_figures.py --project clemson_amp
    python clemson_amp/scripts/poster_figures.py --project clemson_amp --settling-only

The settling calculation is explicitly theoretical. Missing, malformed, negative,
or inconsistent model outputs fail the model-figure workflow; no concentration
or deposition fields are synthesized. Figures show receptor values, not a
simultaneous plume, trajectories, or measured environmental concentrations.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import os
from pathlib import Path
import re
import sys
import tempfile
from datetime import datetime, timezone

# A writable cache also permits completely headless use in the cloud machine.
os.environ.setdefault("MPLCONFIGDIR", str(Path(tempfile.gettempdir()) / "amp-matplotlib"))
os.environ.setdefault("XDG_CACHE_HOME", str(Path(tempfile.gettempdir()) / "amp-cache"))
Path(os.environ["XDG_CACHE_HOME"]).mkdir(parents=True, exist_ok=True)
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib import colors
import numpy as np

from result_provenance import verify_model_result


METRICS = {
    "concentration": ("Concentration", r"$\mu$g m$^{-3}$"),
    "dry_deposition": ("Accumulated dry deposition", r"g m$^{-2}$"),
    "wet_deposition": ("Accumulated wet deposition", r"g m$^{-2}$"),
}
CONSTANTS = {
    "air_density_kg_m3": 1.2,
    "dynamic_viscosity_pa_s": 1.81e-5,
    "air_mean_free_path_m": 65e-9,
    "gravitational_acceleration_m_s2": 9.80616,
}
COMMON_LIMITATIONS = [
    "Hypothetical source, normalized equal emitted mass; no measured AMP validation.",
    "AERMOD is a local steady-state dispersion model; concentration is a period mean and deposition a period accumulation, not synchronous plume snapshots or particle trajectories.",
    "Equivalent spheres do not resolve fibre orientation, polymer degradation, or fragmentation.",
    "Equal mass emissions imply unequal emitted particle numbers across particle cases.",
    "Receptor coverage and resolution constrain the displayed footprint; no long-range transport inference is supported.",
    "AERMOD PERIOD concentration divides by noncalm, nonmissing modeled hours. Deposition sums processed one-hour deposits; missing/calm weather does not supply a validated full-calendar mass estimate.",
    "A zero printed in a fixed-precision PLOTFILE can include a positive value below output precision; grey zero markers are not evidence of physical absence.",
]


def digest(path: Path) -> str:
    with path.open("rb") as stream:
        result = hashlib.file_digest(stream, "sha256")
    return result.hexdigest()


def settling(diameter_um, density_kg_m3, shape_factor=1.0):
    """Stokes + Cunningham settling for equivalent spheres, then divide by χ.

    These constants and the slip formula match AERMOD 26135 VDP1. The dynamic
    shape factor is a separate schematic correction, not an AERMOD parameter.
    Diameter is the numerical equivalent-sphere diameter; do not preconvert it
    to aerodynamic diameter and then supply polymer density again.
    """
    diameter = np.asarray(diameter_um, dtype=float) * 1e-6
    rho = np.asarray(density_kg_m3, dtype=float)
    mean_free_path = CONSTANTS["air_mean_free_path_m"]
    correction = 1 + (2 * mean_free_path / diameter) * (
        1.257 + 0.4 * np.exp(-0.55 * diameter / mean_free_path)
    )
    velocity = (
        np.maximum(rho - CONSTANTS["air_density_kg_m3"], 0)
        * CONSTANTS["gravitational_acceleration_m_s2"]
        * diameter**2
        * correction
        / (18 * CONSTANTS["dynamic_viscosity_pa_s"] * shape_factor)
    )
    reynolds = (
        CONSTANTS["air_density_kg_m3"]
        * velocity
        * diameter
        / CONSTANTS["dynamic_viscosity_pa_s"]
    )
    return velocity, reynolds, correction


def parse_plotfile(path: Path, expected_metric: str) -> dict:
    """Read only conventional, single-result PERIOD AERMOD PLOTFILEs.

    AERMOD PLTANN writes X Y RESULT ZELEV ZHILL ZFLAG AVE GRP N_HOURS
    [NET_ID]. Explicitly locating AVE guards against shifted columns from a
    multiple-result PLOTFILE. Scientific interpretation uses PERIOD, even when
    the filename is annual.plt; full-year completeness needs separate met QA.
    """
    lines = path.read_text(encoding="ascii", errors="strict").splitlines()
    headers = [line for line in lines if line.lstrip().startswith("*")]
    header = "\n".join(headers)
    if not re.search(r"\*\s*AERMOD\s*\(", header):
        raise ValueError(f"{path}: missing authentic AERMOD PLOTFILE header")
    if not re.search(r"PLOT FILE OF\s+PERIOD\b", header):
        raise ValueError(f"{path}: expected PERIOD PLOTFILE, not ANNUAL rates or short-term receptor maxima")
    column_lines = [line for line in headers if re.search(r"\bZELEV\b", line)]
    if not column_lines:
        raise ValueError(f"{path}: no AERMOD column header")
    column_header = column_lines[0].upper()
    expected_labels = {
        "concentration": "CONC",
        "dry_deposition": "DRY",
        "wet_deposition": "WET",
    }
    value_header = column_header.split("ZELEV", 1)[0]
    if expected_labels[expected_metric] not in value_header:
        raise ValueError(f"{path}: header does not identify expected {expected_metric} result")
    points, periods, groups, hours = [], set(), set(), set()
    for number, line in enumerate(lines, 1):
        if not line.strip() or line.lstrip().startswith("*"):
            continue
        fields = line.split()
        if len(fields) < 9 or fields[6] != "PERIOD":
            raise ValueError(f"{path}:{number}: expected one-result PLTANN columns; check PLOTFILE format")
        try:
            numeric = [float(value.replace("D", "E")) for value in fields[:6]]
            count = int(fields[8])
        except ValueError as exc:
            raise ValueError(f"{path}:{number}: unreadable numeric output (including overflow)") from exc
        if not all(math.isfinite(value) for value in numeric):
            raise ValueError(f"{path}:{number}: nonfinite result or coordinates")
        if numeric[2] < 0:
            raise ValueError(f"{path}:{number}: negative {expected_metric} value")
        if count <= 0:
            raise ValueError(f"{path}:{number}: empty modeling period")
        points.append(numeric[:3])
        periods.add(fields[6])
        groups.add(fields[7])
        hours.add(count)
    if not points:
        raise ValueError(f"{path}: no receptor records")
    if len(periods) != 1 or len(groups) != 1 or len(hours) != 1:
        raise ValueError(f"{path}: inconsistent periods, source groups, or time counts")
    if groups != {"ALL"}:
        raise ValueError(f"{path}: expected ALL source group")
    data = np.asarray(points, dtype=float)
    data = data[np.lexsort((data[:, 1], data[:, 0]))]
    if len(np.unique(data[:, :2], axis=0)) != len(data):
        raise ValueError(f"{path}: duplicate receptor coordinates")
    declared = re.search(r"FOR A TOTAL OF\s+(\d+)\s+RECEPTORS", header)
    if declared and int(declared.group(1)) != len(data):
        raise ValueError(f"{path}: declared receptor count differs from parsed records")
    warning_list = []
    if np.count_nonzero(data[:, 2]) == 0:
        warning_list.append("All receptor results are zero; this is not evidence of absent environmental AMP.")
    if periods == {"PERIOD"}:
        warning_list.append("The time count in a PERIOD PLOTFILE is not a substitute for AERMET/AERMOD completeness QA.")
    return {
        "data": data,
        "audit": {
            "path": str(path),
            "sha256": digest(path),
            "receptors": len(data),
            "minimum": float(data[:, 2].min()),
            "maximum": float(data[:, 2].max()),
            "positive_receptors": int(np.count_nonzero(data[:, 2] > 0)),
            "zero_receptors": int(np.count_nonzero(data[:, 2] == 0)),
            "averaging": next(iter(periods)),
            "source_group": next(iter(groups)),
            "hours_in_period" if periods == {"PERIOD"} else "number_of_years": next(iter(hours)),
            "warnings": warning_list,
        },
    }


def save_figure(fig, output: Path, name: str, artifacts: list):
    for extension in ("png", "pdf"):
        path = output / f"{name}.{extension}"
        fig.savefig(path, dpi=300, facecolor="white", bbox_inches="tight")
        artifacts.append({"path": str(path), "sha256": digest(path)})
    plt.close(fig)


def case_label(case: dict) -> str:
    return f"{case['diameter_um']:g} µm; {case['density_g_cm3']:g} g cm⁻³"


def settling_figure(output: Path, artifacts: list) -> dict:
    diameters = np.geomspace(0.5, 40, 350)
    densities = [900.0, 1050.0, 1400.0]
    palette = ["#0072B2", "#D55E00", "#009E73"]
    fig, axes = plt.subplots(1, 2, figsize=(10.4, 4.0), constrained_layout=True)
    for density, color in zip(densities, palette):
        velocity, reynolds, _ = settling(diameters, density)
        axes[0].loglog(diameters, velocity * 1000, color=color, label=f"{density / 1000:g} g cm⁻³")
        axes[1].loglog(diameters, reynolds, color=color)
        for diameter in (1, 10, 30):
            v, re_value, _ = settling(diameter, density)
            axes[0].plot(diameter, v * 1000, "o", color=color, ms=4)
            axes[1].plot(diameter, re_value, "o", color=color, ms=4)
    shape, _, _ = settling(diameters, 1050.0, 2.0)
    axes[0].loglog(diameters, shape * 1000, "--", color=palette[1], label="1.05 g cm⁻³; χ = 2 schematic")
    axes[0].set_ylabel("Settling speed (mm s⁻¹)")
    axes[0].legend(loc="upper left", fontsize=8, frameon=False)
    axes[0].set_title("A. Stokes settling with slip correction")
    axes[1].axhline(0.1, color="#777777", ls=":", lw=1)
    axes[1].text(0.65, 0.12, "Re = 0.1 reference", fontsize=8, color="#555555")
    axes[1].set_ylabel("Particle Reynolds number, ρair v d / μ")
    axes[1].set_title("B. Low-Reynolds-number applicability")
    for ax in axes:
        ax.set_xlabel("Equivalent-sphere diameter (µm)")
        ax.set_xlim(0.5, 40)
        ax.grid(which="major", alpha=0.18, lw=0.6)
    fig.suptitle("Theoretical particle sensitivity — no dispersion-model output", fontsize=12, weight="bold")
    fig.supxlabel("χ = 2 divides the spherical speed by two; illustrative shape sensitivity, not an AERMOD fibre simulation.", fontsize=8)
    save_figure(fig, output, "theoretical_settling", artifacts)
    rows = []
    for density in densities:
        for diameter in (1.0, 10.0, 30.0):
            for factor in (1.0, 2.0):
                velocity, reynolds, correction = settling(diameter, density, factor)
                rows.append({
                    "diameter_um": diameter,
                    "density_kg_m3": density,
                    "dynamic_shape_factor_schematic": factor,
                    "cunningham_factor": float(correction),
                    "settling_velocity_m_s": float(velocity),
                    "settling_velocity_mm_s": float(velocity * 1000),
                    "reynolds_number": float(reynolds),
                    "re_below_0p1": bool(reynolds < 0.1),
                })
    table = output / "theoretical_settling.csv"
    with table.open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    artifacts.append({"path": str(table), "sha256": digest(table)})
    return {
        "type": "analytical calculation, independent of AERMOD results",
        "equation": "v = max(rho_p-rho_air,0) g d^2 Cc / (18 mu chi)",
        "slip_equation": "Cc = 1 + (2 lambda/d) [1.257 + 0.4 exp(-0.55 d/lambda)]",
        "constants": CONSTANTS,
        "diameter_convention": "Equivalent sphere; no additional density-to-aerodynamic-diameter conversion.",
        "shape_caveat": "Chi = 2 is a schematic inverse-speed correction, not measured morphology or an AERMOD input. Slip correction is retained from the sphere approximation.",
        "applicability": "Small Reynolds numbers support Stokes drag for spheres; they do not establish fidelity for airborne fibres or irregular fragments.",
        "reference": "Official AERMOD 26135 soset.f VDP1 density-dependent Stokes and Cunningham formula; EPA AERMOD source distribution.",
        "table": rows,
    }


def scale_for(values):
    positive = np.concatenate([value[value > 0] for value in values])
    if not len(positive):
        return colors.Normalize(0, 1), True
    lower, upper = float(positive.min()), float(positive.max())
    if lower == upper:
        lower, upper = lower / math.sqrt(10), upper * math.sqrt(10)
    return colors.LogNorm(lower, upper), False


def map_figure(scenario: dict, cases: list, results: dict, output: Path,
               name: str, comparison: str, artifacts: list):
    center = scenario["center"]
    fig, axes = plt.subplots(3, len(cases), figsize=(11.5, 10.5), squeeze=False)
    for row, (metric, (label, unit)) in enumerate(METRICS.items()):
        shared_norm, all_zero = scale_for([results[case["name"]][metric]["data"][:, 2] for case in cases])
        color_map = colors.ListedColormap(["#d0d0d0"]) if all_zero else plt.get_cmap("viridis").copy()
        color_map.set_bad("#d0d0d0")
        for column, case in enumerate(cases):
            ax = axes[row, column]
            data = results[case["name"]][metric]["data"]
            east = (data[:, 0] - center["easting_m"]) / 1000
            north = (data[:, 1] - center["northing_m"]) / 1000
            # Every mark is one computed receptor, including zeros in grey.
            values = np.where(data[:, 2] > 0, data[:, 2], np.nan)
            artist = ax.scatter(east, north, c=values, norm=shared_norm,
                                cmap=color_map, marker="s", s=9, linewidths=0,
                                plotnonfinite=True, rasterized=True)
            ax.plot(0, 0, marker="*", color="white", markeredgecolor="black", ms=9, mew=0.6)
            ax.set_aspect("equal")
            ax.set_xlim(east.min() - 0.3, east.max() + 0.3)
            ax.set_ylim(north.min() - 0.3, north.max() + 0.3)
            ax.tick_params(labelsize=8)
            if row == 0:
                ax.set_title(case_label(case), fontsize=11, pad=8)
            if column == 0:
                ax.set_ylabel(f"{label}\nNorth of source (km)", fontsize=10)
            if row == 2:
                ax.set_xlabel("East of source (km)", fontsize=10)
            zero_count = np.count_nonzero(data[:, 2] == 0)
            if zero_count:
                ax.text(0.02, 0.02, f"{zero_count} zeros at output precision: grey", transform=ax.transAxes,
                        fontsize=6.5, bbox={"facecolor": "white", "alpha": 0.85, "edgecolor": "none"})
        bar = fig.colorbar(artist, ax=list(axes[row, :]), fraction=0.026, pad=0.025)
        bar.set_label(f"{label} ({unit})", fontsize=9)
        bar.ax.tick_params(labelsize=8)
        if all_zero:
            bar.set_ticks([])
            bar.ax.text(0.5, 0.5, "All values zero", ha="center", va="center", rotation=90, fontsize=8)
    mass = scenario["source"]["total_emission_g_s"]
    fig.suptitle(f"Illustrative Clemson AMP ({scenario['year']}): {comparison}\nMean concentration / accumulated deposition; equal emission ({mass:g} g s⁻¹ total)", fontsize=14, y=0.99)
    fig.text(0.08, 0.027,
             "★ Hypothetical source. Discrete receptor values; no spatial interpolation. Shared positive-value log scales by row; printed zeros grey.\n"
             "100 m inner grid / 1 km outer grid. Source assumed; no measured AMP concentrations. Deposition is accumulated mass per area over modeled hours.",
             fontsize=8)
    fig.subplots_adjust(left=0.09, right=0.84, bottom=0.09, top=0.90, wspace=0.13, hspace=0.24)
    save_figure(fig, output, name, artifacts)


def profile_figure(scenario: dict, groups: list, results: dict, output: Path, artifacts: list) -> dict:
    center = scenario["center"]
    # Bins reflect the nested grid; this is a sample mean, never an area integral.
    edges = np.r_[np.arange(0, 1001, 100), np.arange(2000, 16001, 1000)] / 1000
    fig, axes = plt.subplots(2, 3, figsize=(11.5, 7.1), sharex=True)
    palette = ["#0072B2", "#D55E00", "#009E73"]
    audit = {}
    for row, (group_label, cases) in enumerate(groups):
        for column, (metric, (label, unit)) in enumerate(METRICS.items()):
            ax = axes[row, column]
            for case, color in zip(cases, palette):
                data = results[case["name"]][metric]["data"]
                distance = np.hypot(data[:, 0] - center["easting_m"], data[:, 1] - center["northing_m"]) / 1000
                bin_id = np.searchsorted(edges, distance, side="right") - 1
                radii, values, counts = [], [], []
                for index in range(len(edges) - 1):
                    included = bin_id == index
                    if np.count_nonzero(included):
                        radii.append(float(distance[included].mean()))
                        values.append(float(data[included, 2].mean()))
                        counts.append(int(np.count_nonzero(included)))
                radii, values = np.asarray(radii), np.asarray(values)
                positive = values > 0
                # Masking preserves gaps at zero rather than plotting a false floor.
                ax.plot(radii, np.where(values > 0, values, np.nan), "o-", ms=3, lw=1.2,
                        label=case_label(case), color=color)
                audit[f"{group_label}/{metric}/{case['name']}"] = {
                    "mean_receptor_radius_km": radii.tolist(),
                    "arithmetic_mean": values.tolist(),
                    "receptors_in_bin": counts,
                    "zero_bins_hidden_from_log_axis": int(np.count_nonzero(~positive)),
                }
            ax.set(xscale="log", yscale="log", xlim=(0.05, 15.5))
            ax.grid(which="major", alpha=0.18, lw=0.6)
            ax.set_ylabel(f"{label} ({unit})", fontsize=9)
            if row == 0:
                ax.set_title(label, fontsize=11)
            if row == 1:
                ax.set_xlabel("Distance from source (km)", fontsize=10)
            if column == 0:
                ax.legend(frameon=False, fontsize=7.5)
                ax.text(0.03, 0.04, group_label, transform=ax.transAxes, fontsize=9)
    fig.suptitle("Particle sensitivity: mean receptor values by distance annulus\nPeriod-mean concentration / accumulated deposition; identical meteorology and equal emissions", fontsize=13)
    fig.text(0.08, 0.025,
             "Arithmetic means across computed receptors in each annulus (100 m bins to 1 km; 1 km bins beyond). Zeros omitted from log axes.\n"
             "These are direction-averaged sample profiles, not downwind trajectories, mass recovery, or a threshold-defined transport range.", fontsize=8)
    fig.subplots_adjust(left=0.08, right=0.98, bottom=0.13, top=0.86, hspace=0.23, wspace=0.30)
    save_figure(fig, output, "particle_distance_profiles", artifacts)
    return {"annulus_edges_km": edges.tolist(), "profiles": audit}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--project", type=Path, default=Path("clemson_amp"))
    parser.add_argument("--settling-only", action="store_true", help="Generate analytical settling figures and table; do not load or claim model results")
    args = parser.parse_args(argv)
    project = args.project.resolve()
    scenario_path = project / "scenario.json"
    scenario = json.loads(scenario_path.read_text())
    output = project / "figures"
    output.mkdir(parents=True, exist_ok=True)
    plt.rcParams.update({
        "font.family": "DejaVu Sans", "font.size": 10,
        "axes.spines.top": False, "axes.spines.right": False,
        "pdf.fonttype": 42, "ps.fonttype": 42,
    })
    artifacts = []
    provenance = {
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "mode": "settling-only" if args.settling_only else "AERMOD period-mean concentration, accumulated deposition, and theoretical settling",
        "status": "in_progress",
        "scenario": {"path": str(scenario_path), "sha256": digest(scenario_path)},
        "script": {"path": str(Path(__file__).resolve()), "sha256": digest(Path(__file__))},
        "result_verifier": {"path": str(Path(__file__).with_name("result_provenance.py")),
                            "sha256": digest(Path(__file__).with_name("result_provenance.py"))},
        "normalization": scenario["source"],
        "limitations": COMMON_LIMITATIONS,
        "artifacts": artifacts,
        "model_outputs": {},
    }
    record = output / ("settling_provenance.json" if args.settling_only else "poster_figures_provenance.json")
    try:
        if not args.settling_only:
            cases = scenario["particle_cases"]
            missing = [project / "aermod" / case["name"] / metric / "annual.plt"
                       for case in cases for metric in METRICS
                       if not (project / "aermod" / case["name"] / metric / "annual.plt").is_file()]
            if missing:
                raise FileNotFoundError("Missing real AERMOD outputs; model figures skipped:\n" + "\n".join(str(path) for path in missing) + "\nUse --settling-only for the independent theoretical calculation.")
            results, reference_xy, reference_time = {}, None, None
            for case in cases:
                results[case["name"]] = {}
                for metric in METRICS:
                    result_path = project / "aermod" / case["name"] / metric / "annual.plt"
                    execution_provenance = verify_model_result(project, result_path)
                    result = parse_plotfile(result_path, metric)
                    audit = result["audit"]
                    audit["verified_native_execution"] = execution_provenance
                    time_key = (audit["averaging"], audit.get("hours_in_period"), audit.get("number_of_years"))
                    if reference_xy is None:
                        reference_xy, reference_time = result["data"][:, :2], time_key
                    elif not np.array_equal(reference_xy, result["data"][:, :2]) or time_key != reference_time:
                        raise ValueError(f"{audit['path']}: receptor coordinates or averaging period differ between cases/metrics")
                    results[case["name"]][metric] = result
                    provenance["model_outputs"][f"{case['name']}/{metric}"] = audit
            size_cases = sorted([case for case in cases if math.isclose(case["density_g_cm3"], 1.05)], key=lambda case: case["diameter_um"])
            density_cases = sorted([case for case in cases if math.isclose(case["diameter_um"], 10)], key=lambda case: case["density_g_cm3"])
            if len(size_cases) != 3 or len(density_cases) != 3:
                raise ValueError("Scenario must contain three 1.05 g/cm³ size cases and three 10 µm density cases")
            map_figure(scenario, size_cases, results, output, "particle_size_maps", "particle size at 1.05 g cm⁻³", artifacts)
            map_figure(scenario, density_cases, results, output, "particle_density_maps", "particle density at 10 µm", artifacts)
            provenance["radial_profiles"] = profile_figure(scenario, [("Size sensitivity", size_cases), ("Density sensitivity", density_cases)], results, output, artifacts)
        provenance["theoretical_settling"] = settling_figure(output, artifacts)
        provenance["status"] = "complete"
    except (OSError, ValueError, KeyError) as exc:
        provenance["status"] = "failed; model figures are not validated for current inputs"
        provenance["error"] = str(exc)
        record.write_text(json.dumps(provenance, indent=2, allow_nan=False) + "\n")
        print(str(exc), file=sys.stderr)
        return 1
    record.write_text(json.dumps(provenance, indent=2, allow_nan=False) + "\n")
    print(f"Saved {len(artifacts)} artifacts and {record}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
