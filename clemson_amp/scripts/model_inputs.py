#!/usr/bin/env python3
"""Generate the Clemson illustrative AERMAP, AERMOD, and AERPLOT decks.

Original repository sample decks are read as templates and never modified.
AERMOD metadata must come from documented station metadata or the AERMET header.
The generated model results represent a hypothetical normalized mass source.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import math
import re
from pathlib import Path

METRICS = {
    "concentration": ("CONC", "MICROGRAMS/M3", "Period-mean concentration (micrograms/m3)"),
    "dry_deposition": ("DDEP", "GRAMS/M2", "Accumulated dry deposition (g/m2)"),
    "wet_deposition": ("WDEP", "GRAMS/M2", "Accumulated wet deposition (g/m2)"),
}


def source_vertex(scenario: dict) -> tuple[float, float]:
    center, source = scenario["center"], scenario["source"]
    return (
        float(center["easting_m"]) - float(source["x_length_m"]) / 2,
        float(center["northing_m"]) - float(source["y_length_m"]) / 2,
    )


def grid_receptors(scenario: dict) -> list[tuple[float, float]]:
    """Return merged centered inner/outer Cartesian grids with no duplicates."""
    domain, center = scenario["domain"], scenario["center"]
    points: set[tuple[float, float]] = set()
    for label in ("outer", "inner"):
        half = float(domain[f"{label}_half_width_m"])
        spacing = float(domain[f"{label}_spacing_m"])
        if half <= 0 or spacing <= 0:
            raise ValueError("Grid half widths and spacings must be positive")
        intervals = 2 * half / spacing
        if not math.isclose(intervals, round(intervals), abs_tol=1e-8):
            raise ValueError(f"{label} grid must contain a whole number of intervals")
        for iy in range(round(intervals) + 1):
            north = float(center["northing_m"]) - half + iy * spacing
            for ix in range(round(intervals) + 1):
                east = float(center["easting_m"]) - half + ix * spacing
                points.add((round(east, 3), round(north, 3)))
    return sorted(points, key=lambda point: (point[1], point[0]))


def write_aermap(base_dir: Path, scenario: dict) -> Path:
    target = base_dir / "aermap"
    target.mkdir(parents=True, exist_ok=True)
    east, north = source_vertex(scenario)
    anchor = scenario["center"]
    source_id = scenario["source"]["id"]
    if int(anchor["epsg"]) != 26917:
        raise ValueError("This input generator requires documented NAD83 / UTM17N (EPSG:26917)")
    points = grid_receptors(scenario)
    lines = [
        "** Hypothetical Clemson AMP source; real USGS terrain, NAD83 UTM17N.",
        "** Merged inner/outer receptor grids; all coordinates are full UTM meters.",
        "CO STARTING",
        "CO TITLEONE Clemson illustrative atmospheric microplastic terrain",
        "CO TITLETWO Unit mass source scenario; not a measured emission inventory",
        "CO DATATYPE NED",
        f"CO DATAFILE ../data/terrain/{scenario['terrain']['filename']}",
        "CO TERRHGTS EXTRACT",
        f"CO ANCHORXY {float(anchor['easting_m']):.3f} {float(anchor['northing_m']):.3f} "
        f"{float(anchor['easting_m']):.3f} {float(anchor['northing_m']):.3f} 17 4",
        "** No DOMAIN restriction: use the provided terrain for critical hill heights.",
        "CO RUNORNOT RUN",
        "CO FINISHED",
        "",
        "SO STARTING",
        f"SO LOCATION {source_id} AREA {east:.3f} {north:.3f}",
        "SO FINISHED",
        "",
        "RE STARTING",
    ]
    lines.extend(f"RE DISCCART {x:.3f} {y:.3f}" for x, y in points)
    lines.extend([
        "RE FINISHED", "", "OU STARTING", "OU RECEPTOR aermap.rec",
        "OU SOURCLOC aermap.src", "OU FINISHED", "",
    ])
    path = target / "aermap.inp"
    path.write_text("\n".join(lines), encoding="ascii")
    return path


def resolve_met_metadata(base_dir: Path, scenario: dict, overrides: dict | None = None) -> dict:
    """Use explicit documented metadata, with station IDs checked against real SFC."""
    metadata = dict(scenario["meteorology"])
    metadata.update({k: v for k, v in (overrides or {}).items() if v is not None})
    surface = base_dir / "aermet" / metadata["surface_file"]
    if surface.is_file():
        with surface.open(encoding="ascii", errors="strict") as stream:
            header = stream.readline()
        for key, label in (("surface_station_id", "SF"), ("upperair_station_id", "UA")):
            match = re.search(rf"\b{label}_ID:\s*(\d+)", header, re.I)
            if match:
                observed_id = match.group(1)
                if key in metadata and int(metadata[key]) != int(observed_id):
                    raise ValueError(f"{key} disagrees with actual AERMET SFC header")
                metadata[key] = observed_id
    required = ("surface_station_id", "upperair_station_id", "profile_base_elevation_m")
    missing = [key for key in required if metadata.get(key) is None]
    if missing:
        raise ValueError("Documented AERMET station metadata required: " + ", ".join(missing))
    for key in required[:2]:
        if not re.fullmatch(r"\d{1,8}", str(metadata[key])):
            raise ValueError(f"{key} must be a numeric station identifier")
    float(metadata["profile_base_elevation_m"])
    return metadata


def model_window(scenario: dict) -> tuple[list[int], str]:
    """Return a validated AERMOD eight-field STARTEND and honest period label."""
    year = int(scenario["year"])
    met = scenario["meteorology"]
    startend = met.get("startend", [year, 1, 1, 1, year, 12, 31, 24])
    if not isinstance(startend, list) or len(startend) != 8:
        raise ValueError("meteorology.startend must be a list of eight integers")
    if any(not isinstance(value, int) or isinstance(value, bool) for value in startend):
        raise ValueError("meteorology.startend must contain integers")
    for offset in (0, 4):
        dt.date(*startend[offset:offset + 3])
        if not 1 <= startend[offset + 3] <= 24:
            raise ValueError("STARTEND hours must follow AERMOD's 1 to 24 convention")
    if tuple(startend[:4]) > tuple(startend[4:]):
        raise ValueError("STARTEND end must not precede start")
    label = met.get("period_label", scenario.get("period_label", f"{year} calendar-year window"))
    return startend, str(label)


def write_aermod(
    base_dir: Path, scenario: dict, case: dict, metric: str, metadata: dict,
    *, receptor_file: str = "../../../aermap/aermap.rec", hourly_postfile: bool = False,
) -> Path:
    if metric not in METRICS:
        raise ValueError(f"Unknown metric: {metric}")
    name = case["name"]
    if not re.fullmatch(r"[A-Za-z0-9_]+", name):
        raise ValueError("Case names must contain letters, digits, and underscores only")
    target = base_dir / "aermod" / name / metric
    target.mkdir(parents=True, exist_ok=True)
    source = scenario["source"]
    source_id = source["id"]
    if not re.fullmatch(r"[A-Za-z0-9_]{1,12}", source_id):
        raise ValueError("Source ID must be 1 to 12 alphanumeric/underscore characters")
    x_length = float(source["x_length_m"])
    y_length = float(source["y_length_m"])
    total_emission = float(source["total_emission_g_s"])
    if x_length <= 0 or y_length <= 0 or total_emission <= 0:
        raise ValueError("Source area and total emission must be positive")
    flux = total_emission / (x_length * y_length)
    diameter = float(case["diameter_um"])
    density = float(case["density_g_cm3"])
    if diameter <= 0 or density <= 0:
        raise ValueError("Particle size and density must be positive")
    output_type = METRICS[metric][0]
    year = int(scenario["year"])
    startend, period_label = model_window(scenario)
    # Explicitly include both dry and wet depletion for all three output types.
    # One metric per run preserves the conventional X,Y,value PLOTFILE layout.
    lines = [
        "** ILLUSTRATIVE NORMALIZED SOURCE: no measured AMP emission inventory.",
        f"** Total mass release {total_emission:g} g/s over {x_length:g} x {y_length:g} m AREA.",
        "** Equivalent spherical particle input; no fiber/film shape model.",
        "CO STARTING",
        "CO TITLEONE Hypothetical Clemson atmospheric microplastic transport",
        "CO TITLETWO " + f"{name} {output_type}: {period_label}"[:68],
        f"CO MODELOPT DFAULT {output_type} DRYDPLT WETDPLT",
        "CO AVERTIME 1 24 PERIOD" if metric == "concentration" else "CO AVERTIME 1 PERIOD",
        "CO POLLUTID AMP",
        "CO RUNORNOT RUN",
        "CO ERRORFIL errors.out",
        "CO FINISHED",
        "",
        "SO STARTING",
        "SO INCLUDED ../../../aermap/aermap.src",
        f"SO SRCPARAM {source_id} {flux:.10g} {float(source['release_height_m']):g} "
        f"{x_length:g} {y_length:g} 0.0 {float(source['initial_vertical_sigma_m']):g}",
        f"SO PARTDIAM {source_id} {diameter:g}",
        f"SO MASSFRAX {source_id} 1.0",
        f"SO PARTDENS {source_id} {density:g}",
        "SO CONCUNIT 1.0E6 GRAMS/SEC MICROGRAMS/M3",
        "SO DEPOUNIT 3600.0 GRAMS/SEC GRAMS/M2",
        "SO SRCGROUP ALL",
        "SO FINISHED",
        "",
        "RE STARTING",
        f"RE INCLUDED {receptor_file}",
        "RE FINISHED",
        "",
        "ME STARTING",
        f"ME SURFFILE ../../../aermet/{metadata['surface_file']}",
        f"ME PROFFILE ../../../aermet/{metadata['profile_file']}",
        f"ME SURFDATA {metadata['surface_station_id']} {year} "
        f"{metadata.get('surface_station_name', metadata.get('surface_icao', 'DOCUMENTED_SURFACE'))}",
        f"ME UAIRDATA {metadata['upperair_station_id']} {year} "
        f"{metadata.get('upperair_station_name', metadata.get('upperair_igra_id', 'DOCUMENTED_UPPER_AIR'))}",
        f"ME PROFBASE {float(metadata['profile_base_elevation_m']):g} METERS",
        "ME STARTEND " + " ".join(map(str, startend)),
        "ME FINISHED",
        "",
        "OU STARTING",
        "OU RECTABLE 1 FIRST",
        "OU RECTABLE 24 FIRST",
        "** annual.plt is the conventional PERIOD-output filename.",
        "** PERIOD: mean concentration, but accumulated deposition in g/m2 (not a mean flux).",
        "** Deposition output is limited to PERIOD totals and 1-hour amounts in g/m2.",
        "** Multi-hour deposition ranks are omitted because v26135 scales output-type1.",
        f"** Requested time window: {period_label}",
        "** Statistics cover valid processed hours in that window; inspect data completeness.",
        "OU PLOTFILE PERIOD ALL annual.plt",
        "** Peak maps combine independent per-receptor maxima, not one plume snapshot.",
        "OU PLOTFILE 1 ALL FIRST max1h.plt",
        "OU PLOTFILE 24 ALL FIRST max24h.plt",
        "OU SUMMFILE aermod.sum",
        "OU FINISHED",
        "",
    ]
    if metric != "concentration":
        lines.remove("OU RECTABLE 24 FIRST")
        lines.remove("OU PLOTFILE 24 ALL FIRST max24h.plt")
    if hourly_postfile:
        lines.insert(lines.index("OU FINISHED"), "OU POSTFILE 1 ALL PLOT hourly.plt")
        lines.insert(0, "** Diagnostic receptors only: hourly output for descriptive weather stratification.")
    path = target / "aermod.inp"
    path.write_text("\n".join(lines), encoding="ascii")
    return path


def write_weather_receptors(base_dir: Path, scenario: dict) -> Path:
    """Copy 16 exact terrain records from the completed AERMAP output."""
    center = scenario["center"]
    targets: set[tuple[float, float]] = set()
    for radius in (500, 1000, 5000, 10000):
        for dx, dy in ((radius, 0), (-radius, 0), (0, radius), (0, -radius)):
            # AERMAP24142 prints source/receptor coordinates to0.01m.
            targets.add((round(float(center["easting_m"]) + dx, 2),
                         round(float(center["northing_m"]) + dy, 2)))
    original = base_dir / "aermap" / "aermap.rec"
    if not original.is_file() or original.stat().st_size == 0:
        raise ValueError("Completed, nonempty aermap/aermap.rec is required for diagnostics")
    records: dict[tuple[float, float], str] = {}
    for line in original.read_text(encoding="ascii").splitlines():
        tokens = line.split()
        if tokens and tokens[0].upper() == "RE":
            tokens = tokens[1:]
        if len(tokens) >= 5 and tokens[0].upper() == "DISCCART":
            coords = (round(float(tokens[1]), 2), round(float(tokens[2]), 2))
            if coords in targets:
                if coords in records:
                    raise ValueError(f"Duplicate AERMAP terrain receptor: {coords}")
                records[coords] = line
    missing = targets - records.keys()
    if missing:
        raise ValueError(f"AERMAP output is missing {len(missing)} required diagnostic receptors")
    target = base_dir / "aermap" / "weather.rec"
    lines = [
        "** Exact AERMAP-generated records: 500/1000/5000/10000 m cardinal receptors.",
        "** Diagnostic observations are descriptive weather contrasts, not causal effects.",
        "RE ELEVUNIT METERS",
    ]
    lines.extend(records[point] for point in sorted(targets, key=lambda point: (point[1], point[0])))
    target.write_text("\n".join(lines) + "\n", encoding="ascii")
    return target


def write_diagnostics(base_dir: Path, scenario: dict, metadata: dict) -> list[Path]:
    """Write a small hourly-output baseline with all original source physics."""
    write_weather_receptors(base_dir, scenario)
    candidates = [case for case in scenario["particle_cases"] if case["name"] == "d10_r1050"]
    if len(candidates) != 1:
        raise ValueError("A single baseline particle case named d10_r1050 is required")
    case = dict(candidates[0], name="diagnostic_d10_r1050")
    return [write_aermod(base_dir, scenario, case, metric, metadata,
                         receptor_file="../../../aermap/weather.rec", hourly_postfile=True)
            for metric in METRICS]


def _replace_aerplot_values(template: str, values: dict[str, str]) -> str:
    result: list[str] = []
    used: set[str] = set()
    for line in template.splitlines():
        if line.strip() and not line.lstrip().startswith(";") and "=" in line:
            key = line.partition("=")[0].strip()
            if key in values:
                line = f"{key}={values[key]}"
                used.add(key)
        result.append(line)
    missing = set(values) - used
    if missing:
        raise ValueError("Sample AERPLOT template lacks required keys: " + ", ".join(sorted(missing)))
    return "\n".join(result) + "\n"


def write_aerplot(base_dir: Path, scenario: dict, case: dict, metric: str, template: str) -> Path:
    target = base_dir / "aerplot" / case["name"] / metric
    target.mkdir(parents=True, exist_ok=True)
    _, period_label = model_window(scenario)
    title = (
        f"Hypothetical Clemson {period_label}: {METRICS[metric][2]}, "
        f"diameter {float(case['diameter_um']):g} um, density {float(case['density_g_cm3']):g} g/cm3, "
        f"source {float(scenario['source']['total_emission_g_s']):g} g/s normalization"
    )
    values = {
        "origin": "UTM", "easting": "0", "northing": "0", "utmZone": "17",
        "inNorthernHemisphere": "true",
        "originLatitude": str(scenario["center"]["latitude"]),
        "originLongitude": str(scenario["center"]["longitude"]),
        "altitudeChoice": "relativeToGround", "altitude": "0",
        "show3DConcentrations": "False", "show3DSources": "False",
        "minimumConcentrationAccepted": "NONE", "maximumConcentrationAccepted": "NONE",
        "PlotFileName": f"../../../aermod/{case['name']}/{metric}/annual.plt",
        "SourceDisplayInputFileName": "",
        "OutputFileNameBase": f"clemson_{case['name']}_{metric}",
        "NameDisplayedInGoogleEarth": title,
        "sDisableEarthBrowser": "true", "sDisableProgressMeter": "false",
        "IconScale": "0.7", "sIconSetChoice": "redBlue",
        "minbin": "data", "maxbin": "data", "binningChoice": "Linear",
        "contourLegendTitleHTML": title,
        "makeContours": "true", "makeGradients": "false",
        "contourExtension": str(math.ceil(1.5 * float(scenario["domain"]["outer_spacing_m"]))),
        "gradientExtension": str(math.ceil(1.5 * float(scenario["domain"]["outer_spacing_m"]))),
        "numberOfTimesToSmoothContourSurface": "1",
    }
    text = _replace_aerplot_values(template, values)
    prefix = (
        "; Generated from repository aerplot.inp sample; original untouched.\n"
        "; PERIOD output: mean concentration or accumulated deposition; hypothetical source.\n"
        "; Deposition PERIOD units g/m2 are accumulated over modeled hours, not mean flux.\n"
        "; Data-driven bins are for inspection; use shared explicit bins for comparisons.\n"
        "; Smoothed contours interpolate receptors and do not increase model resolution.\n"
    )
    path = target / "aerplot.inp"
    path.write_text(prefix + text, encoding="ascii")
    return path


def set_aerplot_common_scale(base_dir: Path, scenario: dict) -> dict:
    """Update only AERPLOT color bounds after verifying all current model fields."""
    from result_provenance import verify_model_result

    pending: list[tuple[Path, str, str, str]] = []
    metrics: dict[str, dict] = {}
    for metric, (_, units, quantity) in METRICS.items():
        cases = []
        maximum = 0.0
        for case in scenario["particle_cases"]:
            name = case["name"]
            result_path = base_dir / "aermod" / name / metric / "annual.plt"
            verified = verify_model_result(base_dir, result_path)
            values = []
            for line in result_path.read_text(encoding="ascii").splitlines():
                if not line.strip() or line.lstrip().startswith("*"):
                    continue
                fields = line.split()
                if len(fields) < 3:
                    raise ValueError(f"Malformed model field record in {result_path}")
                value = float(fields[2])
                if not math.isfinite(value) or value < 0:
                    raise ValueError(f"Nonfinite or negative model field in {result_path}")
                values.append(value)
            if not values:
                raise ValueError(f"No receptor values in {result_path}")
            case_maximum = max(values)
            maximum = max(maximum, case_maximum)
            config_path = base_dir / "aerplot" / name / metric / "aerplot.inp"
            if not config_path.is_file():
                raise ValueError(f"Generate AERPLOT configuration before choosing shared bounds: {config_path}")
            cases.append({"name": name, "receptors": len(values),
                          "field_minimum": min(values), "field_maximum": case_maximum,
                          "model_provenance": verified, "configuration": str(config_path)})
        magnitude = 10 ** math.floor(math.log10(maximum)) if maximum > 0 else 1.0
        upper = math.ceil(maximum / magnitude) * magnitude if maximum > 0 else 1.0
        bounds = {"minbin": "0", "maxbin": f"{upper:.12g}", "binningChoice": "Linear"}
        metrics[metric] = {"quantity": quantity, "units": units, "minimum": 0.0,
                           "maximum": upper, "actual_global_maximum": maximum, "cases": cases}
        for case in cases:
            config_path = Path(case["configuration"])
            text = _replace_aerplot_values(config_path.read_text(encoding="ascii"), bounds)
            text = text.replace("; Data-driven bins are for inspection; use shared explicit bins for comparisons.",
                                "; Explicit shared bounds verified against model fields; see common_scale_provenance.json.")
            # Repeated invocations replace this generated annotation deterministically.
            text = "\n".join(line for line in text.splitlines()
                              if not line.startswith("; Shared verified scale:")) + "\n"
            comment = (f"; Shared verified scale: {metric}, Linear 0 to {upper:.12g} {units}; "
                       f"all {len(cases)} particle cases, current audited PERIOD outputs.\n")
            pending.append((config_path, comment + text, metric, case["name"]))
    # No writes occur until every field and configuration has passed verification.
    for config_path, text, metric, name in pending:
        config_path.write_text(text, encoding="ascii")
        record = next(case for case in metrics[metric]["cases"] if case["name"] == name)
        record["configuration_sha256"] = hashlib.sha256(config_path.read_bytes()).hexdigest()
    document = {"generated_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
                "operation": "AERPLOT configuration color-scale update only; no model inputs regenerated",
                "scaling": "Zero-safe Linear bounds shared across particle cases independently for each quantity",
                "metrics": metrics}
    output = base_dir / "aerplot" / "common_scale_provenance.json"
    output.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")
    return document


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    default_base = Path(__file__).resolve().parents[1]
    parser.add_argument("--scenario", type=Path, default=default_base / "scenario.json")
    parser.add_argument("--base-dir", type=Path, default=None)
    parser.add_argument("--aerplot-template", type=Path, default=None)
    parser.add_argument("--surface-id", dest="surface_station_id")
    parser.add_argument("--upperair-id", dest="upperair_station_id")
    parser.add_argument("--profile-base", dest="profile_base_elevation_m", type=float)
    parser.add_argument("--only-aermap", action="store_true")
    parser.add_argument("--aerplot-common-scale", action="store_true", help="Only update existing AERPLOT configs with shared scales from verified current model results")
    parser.add_argument("--diagnostics", action="store_true", help="Also generate 16-receptor hourly diagnostic decks after AERMAP")
    parser.add_argument("--diagnostics-only", action="store_true", help="Generate only diagnostic receptors and hourly decks")
    args = parser.parse_args()
    scenario = json.loads(args.scenario.read_text(encoding="utf-8"))
    base = (args.base_dir or args.scenario.parent).resolve()
    if args.aerplot_common_scale:
        if args.only_aermap or args.diagnostics or args.diagnostics_only:
            parser.error("--aerplot-common-scale cannot be combined with model-input generation options")
        try:
            provenance = set_aerplot_common_scale(base, scenario)
        except (OSError, ValueError) as error:
            parser.exit(2, f"AERPLOT shared scale requires verified current results: {error}\n")
        for metric, details in provenance["metrics"].items():
            print(f"{metric}: Linear 0 to {details['maximum']:g} {details['units']} across {len(details['cases'])} cases")
        return 0
    overrides = {key: getattr(args, key) for key in (
        "surface_station_id", "upperair_station_id", "profile_base_elevation_m"
    )}
    if args.diagnostics_only:
        try:
            metadata = resolve_met_metadata(base, scenario, overrides)
            paths = write_diagnostics(base, scenario, metadata)
        except ValueError as error:
            parser.exit(2, f"Diagnostics require completed terrain and station metadata: {error}\n")
        print(f"Wrote weather.rec and {len(paths)} hourly diagnostic AERMOD inputs")
        return 0
    aermap = write_aermap(base, scenario)
    print(f"Wrote {aermap}; {len(grid_receptors(scenario))} unique receptors")
    if args.only_aermap:
        return 0
    template_path = args.aerplot_template or base.parent / "aerplot.inp"
    template = template_path.read_text(encoding="ascii")
    # Preserve sample documentation and required key set for all AERPLOT configs.
    for case in scenario["particle_cases"]:
        for metric in METRICS:
            write_aerplot(base, scenario, case, metric, template)
    try:
        metadata = resolve_met_metadata(base, scenario, overrides)
    except ValueError as error:
        parser.exit(2, f"AERMAP/AERPLOT generated; AERMOD requires metadata: {error}\n")
    count = 0
    for case in scenario["particle_cases"]:
        for metric in METRICS:
            write_aermod(base, scenario, case, metric, metadata)
            count += 1
    print(f"Wrote {count} AERMOD and {count} AERPLOT inputs; originals unchanged")
    if args.diagnostics:
        try:
            paths = write_diagnostics(base, scenario, metadata)
        except ValueError as error:
            parser.exit(2, f"Main decks generated; diagnostic setup requires: {error}\n")
        print(f"Wrote weather.rec and {len(paths)} hourly diagnostic AERMOD inputs")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
