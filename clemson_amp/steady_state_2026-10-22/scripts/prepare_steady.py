#!/usr/bin/env python3
"""Prepare deliberately synthetic, time-invariant AERMOD control experiments.

The supplied SFC/PFL records follow the AERMOD26135 interface; they are NOT
AERMET-processed observations. Real AERMAP terrain is reused unchanged.
"""
from __future__ import annotations

import argparse
import csv
from datetime import date
import hashlib
import json
import math
from pathlib import Path
import shutil


METRICS = {"concentration": "CONC", "dry_deposition": "DDEP", "wet_deposition": "WDEP"}
SFC_FIELDS = ["year", "month", "day", "julian_day", "hour_ending_lst",
              "sensible_heat_flux_W_m2", "friction_velocity_m_s", "convective_velocity_scale_m_s",
              "potential_temperature_gradient_above_mixing_height_K_m", "convective_mixing_height_m",
              "mechanical_mixing_height_m", "monin_obukhov_length_m", "roughness_length_m",
              "bowen_ratio", "albedo", "reference_wind_m_s", "wind_from_degrees",
              "wind_reference_height_m", "air_temperature_K", "temperature_reference_height_m",
              "precipitation_code", "precipitation_mm_h", "relative_humidity_percent",
              "surface_pressure_hPa", "cloud_cover_tenths"]
PFL_FIELDS = ["year", "month", "day", "hour_ending_lst", "height_m", "top_of_profile_flag",
              "wind_from_degrees", "wind_speed_m_s", "temperature_C", "sigma_theta_degrees", "sigma_w_m_s"]


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, allow_nan=False) + "\n")


def csv_file(path: Path, rows: list[dict]) -> None:
    with path.open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]), lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def label_number(value: float) -> str:
    return f"{value:g}".replace(".", "p")


def make_case(project: Path, scenario: dict, case: dict) -> list[dict]:
    met = scenario["meteorology"]
    sample_date = date.fromisoformat(scenario["simulation_date"])
    julian = sample_date.timetuple().tm_yday
    wind = case["wind_speed_m_s"]
    # Stable MO correction tends to the neutral log law as L -> +infinity.
    # Use the same L for all cases and calculate the corresponding friction
    # velocity, rather than imposing physically incompatible u and u_star.
    z, z0, length = met["wind_reference_height_m"], met["roughness_length_m"], met["monin_obukhov_length_m"]
    denominator = math.log(z / z0) + 5.0 * (z - z0) / length
    ustar = met["von_karman_constant"] * wind / denominator
    heat = -(met["air_density_kg_m3"] * met["air_specific_heat_J_kg_K"] * met["air_temperature_K"]
             * ustar ** 3 / (met["von_karman_constant"] * met["gravity_m_s2"] * length))
    case.update(friction_velocity_m_s=ustar, sensible_heat_flux_W_m2=heat)
    rain = case["precipitation_mm_h"]
    surface_rows, profile_rows = [], []
    for hour in range(1, scenario["hours"] + 1):
        values = [sample_date.year, sample_date.month, sample_date.day, julian, hour,
                  heat, ustar, -9.0, -9.0, -999.0, met["mechanical_mixing_height_m"],
                  length, z0, met["bowen_ratio"], met["albedo"], wind, met["wind_from_degrees"], z,
                  met["air_temperature_K"], met["temperature_reference_height_m"], 11 if rain > 0 else 0,
                  rain, met["relative_humidity_percent"], met["surface_pressure_hPa"], met["cloud_cover_tenths"]]
        surface_rows.append(dict(zip(SFC_FIELDS, values)))
        profile = [sample_date.year, sample_date.month, sample_date.day, hour, z, 1,
                   met["wind_from_degrees"], wind,
                   met["air_temperature_K"] - 273.15 - 0.0098 * (z - met["temperature_reference_height_m"]),
                   99.0, 99.0]
        profile_rows.append(dict(zip(PFL_FIELDS, profile)))
    # VERSION marks compatibility with the EPA interface, not production by
    # AERMET. IDs are explicit synthetic placeholders and never called KCEU.
    header = ("   34.680N   82.840W          UA_ID: 99999999  SF_ID: 99999     OS_ID: 99999        "
              "VERSION: 26135    SYNTHETIC_CONTROL_NOT_OBSERVATIONS")
    sfc = project / "aermet" / f"{case['name']}.sfc"
    pfl = project / "aermet" / f"{case['name']}.pfl"
    sfc.write_text(header + "\n" + "\n".join(
        " ".join(f"{row[key]:.12g}" for key in SFC_FIELDS) + " PROG-Mod SYNTHETIC"
        for row in surface_rows) + "\n")
    pfl.write_text("\n".join(" ".join(f"{row[key]:.12g}" for key in PFL_FIELDS)
                             for row in profile_rows) + "\n")
    case["surface_file"] = str(sfc.relative_to(project))
    case["profile_file"] = str(pfl.relative_to(project))
    case["surface_file_sha256"] = digest(sfc)
    case["profile_file_sha256"] = digest(pfl)
    case["surface_met_rows"] = surface_rows
    case["profile_met_rows"] = profile_rows
    for metric, option in METRICS.items():
        directory = project / "aermod" / case["name"] / metric
        directory.mkdir(parents=True, exist_ok=True)
        flux = scenario["source"]["total_emission_g_s"] / (
            scenario["source"]["x_length_m"] * scenario["source"]["y_length_m"])
        deck = f"""** SYNTHETIC CONTROLLED STEADY-STATE EXPERIMENT; NOT OBSERVED WEATHER.
** Fixed weather in every hour; source emissions are an illustrative assumption.
** Deposition POSTFILE values are one-hour amounts in ug/m2, numerically ug/m2/h.
CO STARTING
CO TITLEONE Controlled steady-state Clemson microplastic plume
CO TITLETWO {case['name']} {option} synthetic {sample_date.isoformat()}
CO MODELOPT DFAULT {option} DRYDPLT WETDPLT
CO AVERTIME 1 PERIOD
CO POLLUTID AMP
CO RUNORNOT RUN
CO ERRORFIL errors.out
CO FINISHED

SO STARTING
SO INCLUDED ../../../aermap/aermap.src
SO SRCPARAM AMPAREA {flux:.12g} 2 100 100 0.0 1
SO PARTDIAM AMPAREA {scenario['particle']['diameter_um']:.12g}
SO MASSFRAX AMPAREA 1.0
SO PARTDENS AMPAREA {scenario['particle']['density_g_cm3']:.12g}
SO CONCUNIT 1.0E6 GRAMS/SEC MICROGRAMS/M3
SO DEPOUNIT 3.6E9 GRAMS/SEC MICROGRAMS/M2
SO SRCGROUP ALL
SO FINISHED

RE STARTING
RE INCLUDED ../../../aermap/aermap.rec
RE FINISHED

ME STARTING
ME SURFFILE ../../../{case['surface_file']}
ME PROFFILE ../../../{case['profile_file']}
ME SURFDATA 99999 {sample_date.year} SYNTHETIC
ME UAIRDATA 99999999 {sample_date.year} SYNTHETIC
ME PROFBASE {scenario['source']['ground_elevation_m']:.12g} METERS
ME STARTEND {sample_date.year} {sample_date.month} {sample_date.day} 1 {sample_date.year} {sample_date.month} {sample_date.day} {scenario['hours']}
ME FINISHED

OU STARTING
OU FILEFORM EXP
OU RECTABLE 1 FIRST
OU PLOTFILE PERIOD ALL annual.plt
OU PLOTFILE 1 ALL FIRST max1h.plt
OU POSTFILE 1 ALL PLOT hourly.plt
OU SUMMFILE aermod.sum
OU FINISHED
"""
        (directory / "aermod.inp").write_text(deck)
    return [{"case": case["name"], **row} for row in surface_rows]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--source-project", type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument("--terrain-directory", type=Path,
                        help="Validated AERMAP product directory; defaults to SOURCE_PROJECT/aermap")
    parser.add_argument("--year", type=int, default=2024)
    parser.add_argument("--date", help="Controlled calendar label YYYY-MM-DD; default YEAR-07-15")
    parser.add_argument("--source-emission-g-s", type=float, default=10.0 / 86400.0)
    parser.add_argument("--diameter-um", type=float, default=5.0)
    parser.add_argument("--density-g-cm3", type=float, default=1.234)
    parser.add_argument("--pilot-only", action="store_true")
    args = parser.parse_args()
    project, original = args.project.resolve(), args.source_project.resolve()
    if min(args.source_emission_g_s, args.diameter_um, args.density_g_cm3) <= 0:
        parser.error("Source emissions, particle diameter and density must be positive")
    actual_date = date.fromisoformat(args.date or f"{args.year}-07-15")
    if actual_date.year != args.year:
        parser.error("--date and --year differ")
    for directory in ("aermap", "aermet", "aermod"):
        (project / directory).mkdir(parents=True, exist_ok=True)
    parent_scenario = json.loads((original / "scenario.json").read_text())
    terrain_directory = args.terrain_directory.resolve() if args.terrain_directory else original / "aermap"
    terrain = []
    for name in ("aermap.inp", "aermap.rec", "aermap.src", "aermap_validation.json"):
        source = terrain_directory / name
        if not source.is_file():
            if name == "aermap_validation.json":
                continue
            raise FileNotFoundError(source)
        shutil.copy2(source, project / "aermap" / name)
        terrain.append({"source": str(source), "copied_to": str(project / "aermap" / name), "sha256": digest(source)})
    source = {**parent_scenario["source"], "total_emission_g_s": args.source_emission_g_s,
              "ground_elevation_m": 211.44,
              "interpretation": "Hypothetical diffuse vehicle-related tire-wear/resuspension area; assumed constant emission, not a measured facility or source inventory",
              "illustrative_emission_derivation": "10000 assumed vehicles/day * 0.1 km segment * 0.1 g tire wear/(vehicle km) * 0.10 assumed airborne PM10 fraction = 10 g/day; neither traffic nor emission is measured at Clemson"}
    scenario = {
        "title": "Controlled steady-state Clemson atmospheric microplastic plume experiments",
        "status": "Illustrative controlled meteorology and source assumptions; real receptor terrain; not a hindcast or ambient microplastic observation",
        "year": args.year, "simulation_date": actual_date.isoformat(), "hours": 24,
        "time_basis": "Eastern Standard Time UTC-5; hour-ending 01 through 24",
        "calendar_interpretation": "The year and date label a synthetic 24-hour experiment; they do not establish observed weather or measured microplastic emissions on that date",
        "center": parent_scenario["center"], "domain": parent_scenario["domain"], "source": source,
        "particle": {"diameter_um": args.diameter_um, "density_g_cm3": args.density_g_cm3, "mass_fraction": 1.0,
                     "dynamic_shape_factor_chi": 1.0, "shape": "Monodisperse equivalent-sphere surrogate; not explicit fiber/film/fragment aerodynamics",
                     "diameter_note": parent_scenario["particle_assumptions"]["diameter_note"]},
        "terrain": parent_scenario["terrain"], "terrain_reuse": terrain,
        "meteorology": {"status": "Generated directly for controlled experiments; no AERMET execution or meteorological observations are claimed",
                        "interface_version": "26135", "wind_from_degrees": 270.0, "wind_reference_height_m": 10.0,
                        "roughness_length_m": 0.1, "monin_obukhov_length_m": 1e6,
                        "stability_interpretation": "Near-neutral fixed weak-stable limit, positive L=1000000 m; not a Pasquill-class input",
                        "mechanical_mixing_height_m": 1000.0, "convective_mixing_height_m": -999.0,
                        "convective_velocity_scale_m_s": -9.0, "potential_temperature_gradient_above_mixing_height_K_m": -9.0,
                        "air_temperature_K": 293.15, "temperature_reference_height_m": 2.0,
                        "relative_humidity_percent": 80.0, "surface_pressure_hPa": 989.0,
                        "cloud_cover_tenths": 10, "albedo": 0.2, "bowen_ratio": 1.0,
                        "precipitation_code_interpretation": "IPCODE11 denotes liquid rain; IPCODE0 denotes no precipitation",
                        "von_karman_constant": 0.4, "air_density_kg_m3": 1.2,
                        "air_specific_heat_J_kg_K": 1004.0, "gravity_m_s2": 9.80616,
                        "friction_velocity_rule": "u_star = k*u_ref / [ln(z_ref/z0) + 5*(z_ref-z0)/L]",
                        "heat_flux_rule": "H = -rho_air*cp*T_air*u_star^3/(k*g*L)",
                        "wind_comparison_caveat": "Reference wind, derived friction velocity and tiny consistent heat flux vary between speed cases; L, roughness, mixing height, temperature, direction and all other specified conditions are fixed. Every field is time invariant within a case.",
                        "profile_interpretation": "One top-of-profile measurement at 10 m; model derives vertical profiles. Temperature is dry-adiabatically adjusted from the 2 m reference to 10 m. Sigma-theta and sigma-w missing sentinels99 request model derivation; unstable-only quantities use EPA missing sentinels and are not required for positive L."},
        "output_units": {"concentration": "ug/m3", "hourly_dry_deposition": "ug/m2 per one-hour interval; numerically ug/m2/h flux",
                         "hourly_wet_deposition": "ug/m2 per one-hour interval; numerically ug/m2/h flux",
                         "period_dry_deposition": "ug/m2 accumulated across 24 processed hours",
                         "period_wet_deposition": "ug/m2 accumulated across 24 processed hours",
                         "period_concentration": "ug/m3 arithmetic mean across24processedhours",
                         "file_format": "OU FILEFORM EXP, native E13.6 scientific notation"},
        "particle_cases": [],
    }
    receptor_lines = (project / "aermap" / "aermap.rec").read_text().splitlines()
    scenario["receptor_count"] = sum(line.strip().startswith("RE DISCCART") for line in receptor_lines)
    if not scenario["receptor_count"]:
        scenario["receptor_count"] = sum(line.strip().startswith("DISCCART") for line in receptor_lines)
    scenario["terrain_grid_interpretation"] = (
        "Real AERMAP terrain at all receptors; merged original nested grid and refined eastward plume grid"
        if scenario["receptor_count"] > 873 else "Original873realAERMAPterrainreceptors; pilot only")
    winds = [2.0] if args.pilot_only else [1.0, 2.0, 3.5, 5.0, 7.0]
    rains = [1.0] if args.pilot_only else [0.0, 1.0]
    rows = []
    for wind in winds:
        for rain in rains:
            case = {"name": f"u{label_number(wind)}_r{label_number(rain)}", "wind_speed_m_s": wind,
                    "wind_group": "<2 m/s" if wind < 2 else "2-5 m/s" if wind <= 5 else ">5 m/s",
                    "precipitation_mm_h": rain, "precipitation_label": "Rain1mm/h" if rain else "NoRain",
                    "diameter_um": args.diameter_um, "density_g_cm3": args.density_g_cm3}
            rows.extend(make_case(project, scenario, case))
            scenario["particle_cases"].append(case)
    baseline = next(case for case in scenario["particle_cases"] if case["name"] == "u2_r1")
    # Existing native runner verifies these shared preprocessor product paths
    # before running any deck. Their content is the declared synthetic baseline;
    # every actual deck binds its own case-specific SFC/PFL files explicitly.
    shutil.copy2(project / baseline["surface_file"], project / "aermet" / "clemson.sfc")
    shutil.copy2(project / baseline["profile_file"], project / "aermet" / "clemson.pfl")
    csv_file(project / "all_surface_met_inputs.csv", rows)
    profile_rows = [{"case": case["name"], **row} for case in scenario["particle_cases"] for row in case["profile_met_rows"]]
    csv_file(project / "all_profile_met_inputs.csv", profile_rows)
    write_json(project / "scenario.json", scenario)
    print(json.dumps({"project": str(project), "cases": len(scenario["particle_cases"]),
                      "jobs": len(scenario["particle_cases"]) * len(METRICS), "simulation_date": scenario["simulation_date"],
                      "source_emission_g_s": args.source_emission_g_s, "scenario_sha256": digest(project / "scenario.json")}, indent=2))


if __name__ == "__main__":
    main()
