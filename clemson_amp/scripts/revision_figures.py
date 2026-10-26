#!/usr/bin/env python3
"""Render the 2026-10-20 poster revision without replacing original figures.

Native AERMOD PERIOD fields supply the distance profiles. Analytical figures
use a separate Stokes/Cunningham calculation; chi is never applied to the
AERMOD fields. Run from the repository root::

    python clemson_amp/scripts/revision_figures.py --project clemson_amp
"""
from __future__ import annotations

import argparse
import csv
from datetime import datetime, timezone
import json
import math
from pathlib import Path
import re
import sys

from poster_figures import (
    COMMON_LIMITATIONS, CONSTANTS, METRICS, digest, parse_plotfile,
    save_figure, settling, plt, np,
)
from result_provenance import verify_model_result


SIZE_DIAMETERS = (0.5, 1.0, 5.0, 10.0)
SHAPE_FACTORS = (1.0, 2.0, 3.0)
PALETTE = ("#0072B2", "#D55E00", "#009E73", "#CC79A7")


def table(path: Path, rows: list[dict], artifacts: list) -> None:
    if not rows:
        raise ValueError(f"No data for {path}")
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    artifacts.append({"path": str(path), "sha256": digest(path)})


def analytical_speed(diameter_um, density_kg_m3, chi=1.0):
    if np.any(np.asarray(diameter_um) <= 0) or np.any(np.asarray(chi) < 1):
        raise ValueError("Diameter must be positive and dynamic shape factor chi >= 1")
    return settling(diameter_um, density_kg_m3, chi)


def selected_cases(original: dict, revision: dict) -> tuple[list, list]:
    # Adding two cases must not silently change a shared physical input.
    for key in ("year", "center", "domain", "source", "meteorology", "terrain",
                "particle_assumptions"):
        if original[key] != revision[key]:
            raise ValueError(f"Revision changes shared original scenario setting: {key}")
    cases = {case["name"]: case for case in original["particle_cases"]}
    for case in revision["particle_cases"]:
        if case["name"] in cases and case != cases[case["name"]]:
            raise ValueError(f"Revision redefines an original particle case: {case['name']}")
        cases[case["name"]] = case
    size_cases = []
    for diameter in SIZE_DIAMETERS:
        matching = [case for case in cases.values()
                    if math.isclose(case["diameter_um"], diameter)
                    and math.isclose(case["density_g_cm3"], 1.05)]
        if len(matching) != 1:
            raise ValueError(f"Need exactly one {diameter:g} um, 1.05 g/cm3 case")
        size_cases.append(matching[0])
    density_cases = sorted([case for case in original["particle_cases"]
                            if math.isclose(case["diameter_um"], 10)],
                           key=lambda case: case["density_g_cm3"])
    if [case["density_g_cm3"] for case in density_cases] != [0.9, 1.05, 1.4]:
        raise ValueError("Original fixed-size density comparison has changed")
    return size_cases, density_cases


def common_forcing(project: Path, execution: dict) -> dict:
    paths = (project / "aermap" / "aermap.src", project / "aermap" / "aermap.rec",
             project / "aermet" / "clemson.sfc", project / "aermet" / "clemson.pfl")
    inputs = {Path(item["path"]).resolve(): item["sha256"] for item in execution["inputs"]}
    if not all(path.resolve() in inputs for path in paths):
        raise ValueError("Native execution did not bind all shared source/terrain/weather files")
    return {str(path.relative_to(project)): inputs[path.resolve()] for path in paths}


def load_fields(project: Path, cases: list, provenance: dict) -> dict:
    results = {}
    reference_xy = reference_period = forcing = None
    for case in {case["name"]: case for case in cases}.values():
        results[case["name"]] = {}
        for metric in METRICS:
            path = project / "aermod" / case["name"] / metric / "annual.plt"
            execution = verify_model_result(project, path)
            fields = common_forcing(project, execution)
            result = parse_plotfile(path, metric)
            audit = result["audit"]
            audit["verified_native_execution"] = execution
            report = path.with_name("aermod.out").read_text(encoding="ascii")
            hour_counts = {}
            for key, wording in (("requested_hours", r"Hours\s+Were\s+Processed"),
                                 ("calm_hours", r"Calm\s+Hours\s+Identified"),
                                 ("missing_hours", r"Missing\s+Hours\s+Identified")):
                found = {int(value) for value in re.findall(
                    r"A\s+Total\s+of\s+(\d+)\s+" + wording, report, re.IGNORECASE)}
                if len(found) != 1:
                    raise ValueError(f"No unique native {key} counter for {path}")
                hour_counts[key] = found.pop()
            hour_counts["valid_hours"] = (hour_counts["requested_hours"]
                                         - hour_counts["calm_hours"] - hour_counts["missing_hours"])
            if hour_counts != {"requested_hours": 8760, "calm_hours": 390,
                               "missing_hours": 307, "valid_hours": 8063}:
                raise ValueError(f"Unexpected revised-period model hour coverage: {path}: {hour_counts}")
            audit["native_model_hour_counters"] = hour_counts
            period = (audit["averaging"], audit["hours_in_period"], tuple(hour_counts.items()))
            if reference_xy is None:
                reference_xy = result["data"][:, :2]
                reference_period, forcing = period, fields
            elif (not np.array_equal(reference_xy, result["data"][:, :2])
                  or reference_period != period or forcing != fields):
                raise ValueError(f"Shared receptors, period, or forcing differ for {path}")
            if len(result["data"]) != 873:
                raise ValueError(f"Expected 873 full-domain receptors: {path}")
            provenance["model_outputs"][f"{case['name']}/{metric}"] = audit
            results[case["name"]][metric] = result
    provenance["shared_native_forcing_sha256"] = forcing
    return results


def profiles(scenario: dict, size_cases: list, density_cases: list,
             results: dict, output: Path, artifacts: list) -> dict:
    edges = np.r_[np.arange(0, 1001, 100), np.arange(2000, 16001, 1000)] / 1000
    fig, axes = plt.subplots(2, 3, figsize=(12.1, 7.5), sharex=True)
    rows, audit = [], {}
    groups = (("Size sensitivity: 1.05 g cm⁻³", size_cases),
              ("Density sensitivity: 10 µm", density_cases))
    for row, (group, cases) in enumerate(groups):
        for column, (metric, (label, unit)) in enumerate(METRICS.items()):
            ax = axes[row, column]
            for case, color in zip(cases, PALETTE):
                data = results[case["name"]][metric]["data"]
                radius = np.hypot(data[:, 0] - scenario["center"]["easting_m"],
                                  data[:, 1] - scenario["center"]["northing_m"]) / 1000
                bins = np.searchsorted(edges, radius, side="right") - 1
                x, y, counts = [], [], []
                for index in range(len(edges) - 1):
                    included = bins == index
                    count = int(np.count_nonzero(included))
                    if not count:
                        continue
                    x.append(float(radius[included].mean()))
                    y.append(float(data[included, 2].mean()))
                    counts.append(count)
                    rows.append({
                        "comparison": "size" if row == 0 else "density",
                        "case": case["name"], "diameter_um": case["diameter_um"],
                        "density_g_cm3": case["density_g_cm3"], "dynamic_shape_factor_chi": 1,
                        "metric": metric, "unit": "ug/m3" if metric == "concentration" else "g/m2",
                        "annulus_inner_km": float(edges[index]),
                        "annulus_outer_km": float(edges[index + 1]),
                        "mean_receptor_radius_km": x[-1], "arithmetic_mean": y[-1],
                        "receptor_count": count,
                        "zero_receptor_count": int(np.count_nonzero(data[included, 2] == 0)),
                        "zero_at_output_precision": y[-1] == 0,
                        "radius_nonpositive_hidden_from_log_axis": x[-1] <= 0,
                    })
                if sum(counts) != len(data):
                    raise ValueError(f"Annuli omit receptors for {case['name']}/{metric}")
                label_case = (f"{case['diameter_um']:g} µm" if row == 0
                              else f"{case['density_g_cm3']:.2f} g cm⁻³")
                visible = (np.asarray(x) > 0) & (np.asarray(y) > 0)
                ax.plot(x, np.where(visible, y, np.nan), "o-", color=color,
                        ms=3.4, lw=1.4, label=label_case)
                audit[f"{row}/{metric}/{case['name']}"] = {
                    "mean_receptor_radius_km": x, "arithmetic_mean": y,
                    "receptors_in_bin": counts,
                    "zero_bins_hidden_from_log_axis": sum(value == 0 for value in y),
                }
            ax.set(xscale="log", yscale="log", xlim=(0.05, 15.5))
            ax.grid(which="major", alpha=0.18, lw=0.6)
            ax.set_ylabel(f"{label} ({unit})", fontsize=9)
            if row == 0:
                ax.set_title(label, fontsize=11)
            if row == 1:
                ax.set_xlabel("Distance from source (km)", fontsize=10)
            if column == 0:
                ax.legend(frameon=False, fontsize=8.5, loc="upper right")
                ax.text(0.03, 0.035, group, transform=ax.transAxes, fontsize=9)
    fig.suptitle("Particle sensitivity near Clemson, 2023\n"
                 "Mean concentration and accumulated deposition by distance annulus", fontsize=14)
    fig.text(0.075, 0.028,
             "Hypothetical 1 g s⁻¹ source; identical observed weather and equivalent spheres (χ = 1). Arithmetic receptor means, not area integrals.\n"
             "100 m annuli to 1 km; 1 km annuli beyond. Zero means omitted from logarithmic axes; values can be below printed precision.\n"
             "Small wet-deposition means inherit native 10⁻⁵ g m⁻² rounding; averaging does not recover the lost precision.\n"
             "8,063 valid modeled hours. Direction-averaged profiles are not trajectories or threshold-defined transport distances.", fontsize=8)
    fig.subplots_adjust(left=0.075, right=0.985, bottom=0.16, top=0.86,
                        hspace=0.25, wspace=0.31)
    save_figure(fig, output, "particle_distance_profiles_v2", artifacts)
    table(output / "particle_distance_profiles_v2.csv", rows, artifacts)
    return {"annulus_edges_km": edges.tolist(), "profiles": audit,
            "averaging": "Unweighted arithmetic mean of native receptor values in each annulus; no interpolation"}


def theory_figure(output: Path, artifacts: list) -> dict:
    diameters = np.unique(np.r_[np.geomspace(0.5, 10, 350), SIZE_DIAMETERS])
    densities = (900.0, 1050.0, 1400.0)
    colors = PALETTE[:3]
    styles = ("-", "--", ":")
    fig, ax = plt.subplots(figsize=(8.4, 5.5))
    rows = []
    for density, color in zip(densities, colors):
        for chi, style in zip(SHAPE_FACTORS, styles):
            velocity, reynolds, correction = analytical_speed(diameters, density, chi)
            ax.loglog(diameters, velocity * 1000, color=color, ls=style, lw=1.7)
            if chi == 1:
                marker_speed, _, _ = analytical_speed(SIZE_DIAMETERS, density, chi)
                ax.plot(SIZE_DIAMETERS, marker_speed * 1000, "o", color=color, ms=4)
            for diameter, speed, re_value, cc in zip(diameters, velocity, reynolds, correction):
                rows.append({"diameter_um": float(diameter), "density_kg_m3": density,
                             "dynamic_shape_factor_chi": chi, "cunningham_factor": float(cc),
                             "settling_velocity_m_s": float(speed),
                             "settling_velocity_mm_s": float(speed * 1000),
                             "reynolds_number": float(re_value)})
    from matplotlib.lines import Line2D
    density_handles = [Line2D([0], [0], color=color, lw=2,
                             label=f"{density/1000:g} g cm⁻³")
                       for density, color in zip(densities, colors)]
    first = ax.legend(handles=density_handles, title="Particle density", loc="upper left",
                      frameon=False, fontsize=9, title_fontsize=10)
    ax.add_artist(first)
    ax.legend(handles=[Line2D([0], [0], color="#333333", ls=style, lw=1.7,
                             label=f"χ = {chi:g}" + (" (sphere)" if chi == 1 else " (sensitivity)"))
                       for chi, style in zip(SHAPE_FACTORS, styles)],
              title="Dynamic shape factor", loc="lower right", frameon=False,
              fontsize=9, title_fontsize=10)
    ax.set(xlim=(0.5, 10), xlabel="Volume-equivalent diameter (µm)",
           ylabel="Settling velocity (mm s⁻¹)")
    ax.set_xticks([0.5, 1, 5, 10], ["0.5", "1", "5", "10"])
    ax.grid(which="major", alpha=0.18, lw=0.6)
    ax.set_title("Theoretical settling with dynamic shape factor χ\n"
                 "Stokes drag and equivalent-sphere Cunningham slip correction", fontsize=13, pad=12)
    fig.text(0.125, 0.025,
             "Markers: 0.5, 1, 5, and 10 µm spheres. χ = 2 and 3 are illustrative sensitivities, not morphotype constants.\n"
             "At fixed volume and density, vχ = vsphere / χ. Separate analytical calculation; shape is not changed in AERMOD.\n"
             "Sphere slip correction is an approximation for nonspherical particles; particle orientation is not resolved.", fontsize=8)
    fig.subplots_adjust(left=0.125, right=0.98, bottom=0.24, top=0.84)
    save_figure(fig, output, "theoretical_settling_v2", artifacts)
    table(output / "theoretical_settling_v2.csv", rows, artifacts)
    return {"panels": 1, "density_kg_m3": list(densities),
            "dynamic_shape_factors": list(SHAPE_FACTORS),
            "shape_factors_status": "Illustrative sensitivities; not assigned to a morphotype",
            "diameter_range_um": [0.5, 10], "marker_diameters_um": list(SIZE_DIAMETERS),
            "maximum_reynolds_number": max(row["reynolds_number"] for row in rows)}


def shape_factor_figure(output: Path, artifacts: list, source: dict) -> dict:
    """Optional literature annotations require explicit reported/reference chi.

    Sidecar schema: entries=[{morphotype, chi_min, chi_max, label, source_id,
    interpretation}], unavailable=[str,...], chi_axis_max=number. Missing values
    stay unassigned and are never imputed from a morphotype name.
    """
    entries = source.get("entries", [])
    unavailable = source.get("unavailable", [])
    xmax = max(1.2, float(source.get("chi_axis_max", 5)),
               max((float(item["chi_max"]) for item in entries), default=1.0) * 1.08)
    reference_factors = [float(item[key]) for item in entries
                         for key in ("chi_min", "chi_max")]
    chi = np.unique(np.r_[np.linspace(1, xmax, 400), reference_factors])
    speed, re_value, cc = analytical_speed(10, 1050, chi)
    fig, ax = plt.subplots(figsize=(8.4, 5.6))
    ax.plot(chi, speed * 1000, color="#292929", lw=2,
            label=r"Fixed-volume settling: $v_\chi = v_{\mathrm{sphere}}/\chi$")
    sphere_speed, _, _ = analytical_speed(10, 1050, 1)
    ax.plot([1], [sphere_speed * 1000], "o", color="#292929", ms=6,
            label="Sphere / ideal bead: χ = 1")
    comparisons = []
    for index, entry in enumerate(entries):
        lo, hi = float(entry["chi_min"]), float(entry["chi_max"])
        if lo < 1 or hi < lo:
            raise ValueError(f"Invalid dynamic shape-factor range: {entry}")
        if lo == hi == 1:
            continue  # Sphere reference already has its own clear legend entry.
        values = np.linspace(lo, hi, 100) if hi > lo else np.array([lo])
        velocity, _, _ = analytical_speed(10, 1050, values)
        label = entry.get("label", entry["morphotype"]).replace("chi", "χ")
        color = PALETTE[index % len(PALETTE)]
        if hi > lo:
            ax.plot(values, velocity * 1000, color=color, lw=6, alpha=0.8, label=label)
        else:
            ax.plot(values, velocity * 1000, "o", color=color, ms=7, label=label)
        low_velocity, _, _ = analytical_speed(10, 1050, hi)
        high_velocity, _, _ = analytical_speed(10, 1050, lo)
        comparisons.append({**entry, "settling_velocity_min_mm_s": float(low_velocity * 1000),
                            "settling_velocity_max_mm_s": float(high_velocity * 1000)})
    ax.set(xlim=(0.95, xmax), ylim=(0, float(sphere_speed * 1000) * 1.10),
           xlabel="Dynamic shape factor χ (dimensionless)",
           ylabel="Settling velocity (mm s⁻¹)")
    ax.grid(alpha=0.18, lw=0.6)
    ax.legend(frameon=False, fontsize=8.5, loc="upper right",
              title="Aerosol reference geometries", title_fontsize=9)
    ax.set_title("Settling velocity decreases as dynamic shape factor increases\n"
                 "Fixed volume-equivalent diameter: 10 µm; density: 1.05 g cm⁻³", fontsize=12.5, pad=12)
    note = source.get("figure_note", "Morphotype labels alone do not determine χ; literature comparisons need specific geometry and orientation.").replace("chi", "χ")
    import textwrap
    wrapped = "\n".join(textwrap.wrap(note, width=112))
    fig.text(0.125, 0.045, wrapped +
             "\nReference χ values: Hinds, Aerosol Technology (2nd ed.), via the cited Particula implementation; see source ledger."
             "\nAnalytical sensitivity in air with equivalent-sphere slip correction; no morphology-specific dispersion run.",
             fontsize=8)
    fig.subplots_adjust(left=0.125, right=0.98, bottom=0.25, top=0.84)
    save_figure(fig, output, "settling_velocity_vs_chi", artifacts)
    rows = [{"diameter_um": 10.0, "density_kg_m3": 1050.0,
             "dynamic_shape_factor_chi": float(factor), "cunningham_factor": float(cc),
             "settling_velocity_m_s": float(velocity),
             "settling_velocity_mm_s": float(velocity * 1000),
             "reynolds_number": float(reynolds)}
            for factor, velocity, reynolds in zip(chi, speed, re_value)]
    table(output / "settling_velocity_vs_chi.csv", rows, artifacts)
    return {"diameter_um": 10, "density_kg_m3": 1050,
            "chi_range": [1, xmax], "literature_comparisons": comparisons,
            "unassigned_morphotypes": unavailable, "source_ledger": source}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", type=Path, default=Path("clemson_amp"))
    parser.add_argument("--revision", type=Path, default=Path("revisions/2026-10-20"),
                        help="Revision directory, relative to project unless absolute")
    parser.add_argument("--settling-only", action="store_true")
    parser.add_argument("--chi-data", type=Path,
                        help="Literature dynamic-shape-factor JSON ledger (default: revision/morphotype_shape_factors.json)")
    args = parser.parse_args(argv)
    project = args.project.resolve()
    revision = (args.revision if args.revision.is_absolute() else project / args.revision).resolve()
    output = revision / "figures"
    output.mkdir(parents=True, exist_ok=True)
    scenario_path = project / "scenario.json"
    revision_scenario = revision / "scenario_particle_sizes.json"
    chi_path = (args.chi_data.resolve() if args.chi_data
                else revision / "morphotype_shape_factors.json")
    plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 10,
                         "axes.spines.top": False, "axes.spines.right": False,
                         "pdf.fonttype": 42, "ps.fonttype": 42})
    artifacts = []
    provenance = {
        "created_utc": datetime.now(timezone.utc).isoformat(), "status": "in_progress",
        "script": {"path": str(Path(__file__).resolve()), "sha256": digest(Path(__file__))},
        "dependencies": [{"path": str(Path(__file__).with_name(name)),
                          "sha256": digest(Path(__file__).with_name(name))}
                         for name in ("poster_figures.py", "result_provenance.py")],
        "mode": "analytical settling only" if args.settling_only else "AERMOD distance profiles and separate analytical settling",
        "scenario": {"path": str(scenario_path), "sha256": digest(scenario_path)},
        "constants": CONSTANTS, "limitations": COMMON_LIMITATIONS,
        "equation": "v = (rho_p-rho_air) g d_ve^2 Cc(d_ve) / (18 mu chi)",
        "slip_equation": "Cc = 1 + (2 lambda/d_ve) [1.257 + 0.4 exp(-0.55 d_ve/lambda)]",
        "shape_factor_caveat": "Dynamic shape factor chi is a drag correction at fixed particle volume. Applying spherical Cunningham slip to nonspheres is approximate. Analytical chi changes do not alter any AERMOD run.",
        "artifacts": artifacts, "model_outputs": {},
    }
    record = output / ("settling_revision_provenance.json" if args.settling_only
                       else "revision_figures_provenance.json")
    try:
        provenance["accompanying_documents"] = [
            {"path": str(path), "sha256": digest(path)}
            for path in (revision / "particle_distance_profiles_v2_data_description.txt",
                         revision / "meteorology_summary.json",
                         revision / "settling_figures_methods.txt",
                         revision / "literature_notes.md",
                         revision / "literature_retrieval.json")
            if path.is_file()
        ]
        if not args.settling_only:
            scenario = json.loads(scenario_path.read_text())
            revised = json.loads(revision_scenario.read_text())
            provenance["additional_particle_scenario"] = {
                "path": str(revision_scenario), "sha256": digest(revision_scenario)}
            size_cases, density_cases = selected_cases(scenario, revised)
            results = load_fields(project, size_cases + density_cases, provenance)
            provenance["radial_profiles"] = profiles(scenario, size_cases, density_cases,
                                                     results, output, artifacts)
        provenance["theoretical_settling"] = theory_figure(output, artifacts)
        if not chi_path.is_file():
            raise FileNotFoundError(f"Missing literature shape-factor ledger: {chi_path}")
        chi_source = json.loads(chi_path.read_text())
        provenance["morphotype_shape_factor_source"] = {"path": str(chi_path), "sha256": digest(chi_path)}
        provenance["shape_factor_plot"] = shape_factor_figure(output, artifacts, chi_source)
        provenance["status"] = "complete"
    except (OSError, ValueError, KeyError, TypeError) as exc:
        provenance["status"] = "failed; do not use figures as a validated revision"
        provenance["error"] = str(exc)
        record.write_text(json.dumps(provenance, indent=2, allow_nan=False) + "\n")
        print(str(exc), file=sys.stderr)
        return 1
    record.write_text(json.dumps(provenance, indent=2, allow_nan=False) + "\n")
    print(f"Saved {len(artifacts)} revised artifacts and {record}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
