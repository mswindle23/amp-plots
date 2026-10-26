#!/usr/bin/env python3
"""Create an auditable Excel workbook and PNGs from controlled native AERMOD runs.

This script never synthesizes dispersion or deposition fields. Every plotted
quantity comes from a verified native PERIOD or concurrent hourly POSTFILE.
"""
from __future__ import annotations

import argparse
import csv
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import re
import shlex
import sys

os.environ.setdefault("MPLCONFIGDIR", "/tmp/amp-steady-matplotlib")
os.environ.setdefault("XDG_CACHE_HOME", "/tmp/amp-steady-cache")
Path(os.environ["MPLCONFIGDIR"]).mkdir(parents=True, exist_ok=True)
Path(os.environ["XDG_CACHE_HOME"]).mkdir(parents=True, exist_ok=True)
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib import colors
import numpy as np
import xlsxwriter

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
from result_provenance import verify_model_result

METRICS = ("concentration", "dry_deposition", "wet_deposition")
LABELS = {"concentration": "Concentration (µg m⁻³)",
          "dry_deposition": "Dry deposition flux (µg m⁻² h⁻¹)",
          "wet_deposition": "Wet deposition flux (µg m⁻² h⁻¹)"}
COLORS = ("#0072B2", "#E69F00", "#009E73", "#CC79A7", "#D55E00")
SFC_FIELDS = ("year", "month", "day", "julian_day", "hour_ending_lst",
              "sensible_heat_flux_W_m2", "friction_velocity_m_s", "convective_velocity_m_s",
              "potential_temperature_gradient_K_m", "convective_mixing_height_m",
              "mechanical_mixing_height_m", "Monin_Obukhov_length_m", "roughness_length_m",
              "Bowen_ratio", "albedo", "reference_wind_m_s", "wind_from_degrees",
              "wind_reference_height_m", "reference_temperature_K", "temperature_reference_height_m",
              "precipitation_code", "precipitation_mm_h", "relative_humidity_percent",
              "station_pressure_hPa", "cloud_cover_tenths")
PFL_FIELDS = ("year", "month", "day", "hour_ending_lst", "height_m", "top_flag",
              "wind_from_degrees", "wind_speed_m_s", "temperature_degC",
              "sigma_A_degrees", "sigma_W_m_s")
PERIOD_FIELDS = ("case", "wind_speed_m_s", "wind_group", "rain_mm_h", "x_m", "y_m",
                 "terrain_elevation_m", "hill_height_m", "flagpole_height_m", "source_group",
                 "requested_hours", "concentration_ug_m3", "dry_accumulated_ug_m2",
                 "wet_accumulated_ug_m2", "dry_flux_ug_m2_h", "wet_flux_ug_m2_h", "net_id", "native_averaging")
HOURLY_FIELDS = ("case", "wind_speed_m_s", "wind_group", "rain_mm_h", "date_hour_native",
                 "hour_ending_lst", "x_m", "y_m", "terrain_elevation_m", "hill_height_m",
                 "flagpole_height_m", "source_group", "concentration_ug_m3",
                 "dry_hour_amount_ug_m2", "wet_hour_amount_ug_m2", "dry_flux_ug_m2_h",
                 "wet_flux_ug_m2_h", "net_id", "native_averaging")


def digest(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def record(path: Path) -> dict:
    return {"path": str(path.resolve()), "sha256": digest(path), "bytes": path.stat().st_size}


def wind_group(speed: float) -> str:
    return "<2 m/s" if speed < 2 else "2-5 m/s" if speed <= 5 else ">5 m/s"


def bindings(deck: Path) -> dict[tuple, list[str]]:
    result = {}
    for line in deck.read_text().splitlines():
        if not line.strip() or line.lstrip().startswith(("**", "!", "#")):
            continue
        fields = shlex.split(line)
        if len(fields) >= 3:
            result[tuple(x.upper() for x in fields[:2])] = fields[2:]
    return result


@dataclass
class NativeResult:
    path: Path
    numeric: np.ndarray
    averaging: np.ndarray
    groups: np.ndarray
    time_tags: np.ndarray
    networks: np.ndarray
    ranks: np.ndarray
    header: str


def read_native(path: Path, metric: str, period: bool = False, maximum: bool = False) -> NativeResult:
    numbers, averages, groups, tags, networks, ranks, headers = [], [], [], [], [], [], []
    with path.open(encoding="ascii") as stream:
        for line_number, line in enumerate(stream, 1):
            if line.lstrip().startswith("*"):
                headers.append(line.rstrip())
                continue
            if not line.strip():
                continue
            fields = line.split()
            expected = "PERIOD" if period else "1-HR"
            allowed_lengths = (10, 11) if maximum else (9, 10)
            if len(fields) not in allowed_lengths or fields[6] != expected or fields[7] != "ALL":
                raise ValueError(f"{path}:{line_number}: unexpected native single-metric columns")
            values = [float(x.replace("D", "E")) for x in fields[:6]]
            if not all(math.isfinite(x) for x in values) or values[2] < 0:
                raise ValueError(f"{path}:{line_number}: invalid native numeric values")
            numbers.append(values)
            averages.append(fields[6]); groups.append(fields[7])
            if maximum:
                if fields[8] != "1ST":
                    raise ValueError(f"{path}:{line_number}: only first-ranked one-hour maxima expected")
                tags.append(int(fields[-1])); ranks.append(fields[8])
                networks.append(fields[9] if len(fields) == 11 else "")
            else:
                tags.append(int(fields[8])); ranks.append("")
                networks.append(fields[9] if len(fields) == 10 else "")
    header = "\n".join(headers)
    name = {"concentration": "CONC", "dry_deposition": "DRY", "wet_deposition": "WET"}[metric]
    columns = next((line.split("ZELEV")[0] for line in headers if "ZELEV" in line), "")
    if not re.search(r"\*\s*AERMOD\s*\(", header) or name not in columns or not numbers:
        raise ValueError(f"{path}: authentic {metric} native header/data missing")
    data = np.asarray(numbers, dtype=float)
    tags = np.asarray(tags, dtype=np.int64)
    order = np.lexsort((data[:, 1], data[:, 0])) if maximum else np.lexsort((data[:, 1], data[:, 0], tags))
    keys = np.column_stack((tags, data[:, :2]))
    if len(np.unique(keys, axis=0)) != len(keys):
        raise ValueError(f"{path}: duplicate time/receptor records")
    return NativeResult(path, data[order], np.asarray(averages)[order], np.asarray(groups)[order],
                        tags[order], np.asarray(networks)[order], np.asarray(ranks)[order], header)


def resolve_output(directory: Path, deck: dict, output_keyword: str, averaging: str) -> Path:
    # The output cards may repeat, so read the actual deck rather than a dict.
    for line in (directory / "aermod.inp").read_text().splitlines():
        fields = shlex.split(line)
        if len(fields) >= 5 and fields[:2] == ["OU", output_keyword] and fields[2].upper() == averaging:
            if output_keyword == "POSTFILE":
                return directory / fields[5]
            return directory / fields[4]
    raise ValueError(f"No {averaging} {output_keyword} binding in {directory}")


def same_structure(first: NativeResult, other: NativeResult) -> bool:
    return (np.array_equal(first.numeric[:, [0, 1, 3, 4, 5]], other.numeric[:, [0, 1, 3, 4, 5]])
            and np.array_equal(first.time_tags, other.time_tags)
            and np.array_equal(first.averaging, other.averaging)
            and np.array_equal(first.groups, other.groups)
            and np.array_equal(first.networks, other.networks))


def read_met(path: Path, fields: tuple) -> list[list]:
    rows = []
    for line_number, line in enumerate(path.read_text().splitlines(), 1):
        parts = line.split()
        if not parts or not re.fullmatch(r"\d{2,4}", parts[0]):
            continue
        if len(parts) < len(fields):
            raise ValueError(f"{path}:{line_number}: incomplete meteorological row")
        values = [float(value) for value in parts[:len(fields)]]
        rows.append(values + [" ".join(parts[len(fields):])])
    if not rows:
        raise ValueError(f"No meteorological input rows in {path}")
    return rows


def load_all(project: Path) -> tuple[dict, list[dict], dict]:
    """Return scenario JSON, verified case dictionaries, and complete field audit."""
    project = project.resolve()
    scenario = json.loads((project / "scenario.json").read_text())
    audit = {"model_outputs": {}, "native_output_counts": {}, "steady_checks": {}}
    cases = []
    for directory in sorted((project / "aermod").glob("*")):
        if not (directory / "concentration" / "aermod.inp").is_file():
            continue
        deck = bindings(directory / "concentration" / "aermod.inp")
        surface = (directory / "concentration" / deck[("ME", "SURFFILE")][0]).resolve()
        profile = (directory / "concentration" / deck[("ME", "PROFFILE")][0]).resolve()
        sfc = read_met(surface, SFC_FIELDS)
        pfl = read_met(profile, PFL_FIELDS)
        wind, rain = sfc[0][15], sfc[0][21]
        if any(row[5:] != sfc[0][5:] for row in sfc[1:]):
            raise ValueError(f"{directory.name}: surface conditions vary within controlled run")
        case = {"case": directory.name, "wind_speed_m_s": wind, "wind_group": wind_group(wind),
                "rain_mm_h": rain, "surface": surface, "profile": profile,
                "sfc_rows": sfc, "pfl_rows": pfl, "period": {}, "hourly": {}, "maximum": {}, "native": {}}
        for metric in METRICS:
            metric_dir = directory / metric
            cards = bindings(metric_dir / "aermod.inp")
            period_path = resolve_output(metric_dir, cards, "PLOTFILE", "PERIOD")
            hourly_path = resolve_output(metric_dir, cards, "POSTFILE", "1")
            execution = verify_model_result(project, period_path)
            hourly_execution = verify_model_result(project, hourly_path)
            period = read_native(period_path, metric, True)
            hourly = read_native(hourly_path, metric, False)
            maximum_path = metric_dir / "max1h.plt"
            maximum_execution = verify_model_result(project, maximum_path)
            maximum = read_native(maximum_path, metric, False, True)
            if not np.array_equal(maximum.numeric[:, [0, 1, 3, 4, 5]], period.numeric[:, [0, 1, 3, 4, 5]]):
                raise ValueError(f"{directory.name}/{metric}: max1h coordinates differ from PERIOD")
            factor = (1e6 / float(cards[("SO", "CONCUNIT")][0]) if metric == "concentration"
                      else 3.6e9 / float(cards[("SO", "DEPOUNIT")][0]))
            case["native"][metric] = {"period": period, "hourly": hourly, "maximum": maximum,
                                        "factor_to_canonical": factor}
            case["period"][metric] = period.numeric[:, 2] * factor
            case["hourly"][metric] = hourly.numeric[:, 2] * factor
            case["maximum"][metric] = maximum.numeric[:, 2] * factor
            audit["model_outputs"][f"{directory.name}/{metric}"] = {
                "period": record(period_path), "hourly": record(hourly_path),
                "execution": execution, "hourly_execution": hourly_execution,
                "maximum": record(maximum_path), "maximum_execution": maximum_execution,
                "native_to_canonical_factor": factor,
            }
            if metric != "concentration":
                for kind in ("period", "hourly"):
                    if not same_structure(case["native"]["concentration"][kind], case["native"][metric][kind]):
                        raise ValueError(f"{directory.name}: {metric} receptor/time metadata differ")
        count = len(case["period"]["concentration"])
        hourly = case["native"]["concentration"]["hourly"]
        times, time_counts = np.unique(hourly.time_tags, return_counts=True)
        if count < 873 or len(times) != 24 or not np.all(time_counts == count):
            raise ValueError(f"{directory.name}: expected24 hours andthefullreceptorgrid")
        case["hours"] = len(times); case["times"] = times; case["receptors"] = count
        if not np.all(case["native"]["concentration"]["period"].time_tags == len(times)):
            raise ValueError(f"{directory.name}: PERIOD hour counts differ")
        checks = {}
        for metric in METRICS:
            matrix = case["hourly"][metric].reshape((len(times), count))
            variation = float(np.max(np.abs(matrix - matrix[0])))
            tolerance = max(float(matrix.max()) * 3e-6, 1e-25)
            if variation > tolerance:
                raise ValueError(f"{directory.name}/{metric}: hourly fields are not steady ({variation})")
            target = matrix.mean(axis=0) if metric == "concentration" else matrix.sum(axis=0)
            error = float(np.max(np.abs(target - case["period"][metric])))
            if not np.allclose(target, case["period"][metric], rtol=1.2e-5, atol=1e-25):
                raise ValueError(f"{directory.name}/{metric}: PERIOD disagrees with native hourly aggregation")
            if not np.allclose(matrix.max(axis=0), case["maximum"][metric], rtol=1.2e-5, atol=1e-25):
                raise ValueError(f"{directory.name}/{metric}: max1h disagrees with native hourly maximum")
            checks[metric] = {"maximum_hourly_variation": variation, "maximum_aggregation_error": error}
        audit["steady_checks"][directory.name] = checks
        audit["native_output_counts"][directory.name] = {"period_receptors": count, "hours": len(times),
                                                         "hourly_receptor_rows_per_metric": len(hourly.numeric)}
        cases.append(case)
    if len(cases) != 10:
        raise ValueError(f"Expected10 wind/rain scenarios, found{len(cases)}")
    cases.sort(key=lambda item: (item["wind_speed_m_s"], item["rain_mm_h"]))
    expected = {(speed, rain) for speed in (1., 2., 3.5, 5., 7.) for rain in (0., 1.)}
    if {(case["wind_speed_m_s"], case["rain_mm_h"]) for case in cases} != expected:
        raise ValueError("Case wind/rain combinations differ from requested controlled design")
    return scenario, cases, audit


def period_rows(cases):
    for case in cases:
        native = case["native"]["concentration"]["period"]
        for index, data in enumerate(native.numeric):
            dry, wet = case["period"]["dry_deposition"][index], case["period"]["wet_deposition"][index]
            yield (case["case"], case["wind_speed_m_s"], case["wind_group"], case["rain_mm_h"],
                   data[0], data[1], data[3], data[4], data[5], native.groups[index], case["hours"],
                   case["period"]["concentration"][index], dry, wet, dry/case["hours"], wet/case["hours"], native.networks[index], native.averaging[index])


def hourly_rows(cases):
    for case in cases:
        native = case["native"]["concentration"]["hourly"]
        for index, data in enumerate(native.numeric):
            dry, wet = case["hourly"]["dry_deposition"][index], case["hourly"]["wet_deposition"][index]
            tag = int(native.time_tags[index])
            yield (case["case"], case["wind_speed_m_s"], case["wind_group"], case["rain_mm_h"], tag, tag % 100,
                   data[0], data[1], data[3], data[4], data[5], native.groups[index],
                   case["hourly"]["concentration"][index], dry, wet, dry, wet, native.networks[index], native.averaging[index])


def maximum_rows(cases):
    for case in cases:
        native = case["native"]["concentration"]["maximum"]
        for index, data in enumerate(native.numeric):
            yield (case["case"], case["wind_speed_m_s"], case["rain_mm_h"], data[0], data[1],
                   data[3], data[4], data[5], native.groups[index],
                   int(native.time_tags[index]), case["maximum"]["concentration"][index],
                   int(case["native"]["dry_deposition"]["maximum"].time_tags[index]),
                   case["maximum"]["dry_deposition"][index],
                   int(case["native"]["wet_deposition"]["maximum"].time_tags[index]),
                   case["maximum"]["wet_deposition"][index], native.networks[index], native.averaging[index], native.ranks[index])


def csv_table(path: Path, headers: tuple, rows) -> int:
    count = 0
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.writer(stream, lineterminator="\n")
        writer.writerow(headers)
        for row in rows:
            writer.writerow(row); count += 1
    return count


def center(scenario):
    return float(scenario["center"]["easting_m"]), float(scenario["center"]["northing_m"])


def receptor_index(case, target_x, target_y, tolerance_m=0.1):
    xy = case["native"]["concentration"]["period"].numeric[:, :2]
    distance = np.hypot(xy[:, 0]-target_x, xy[:, 1]-target_y)
    index = int(distance.argmin())
    if distance[index] > tolerance_m:
        raise ValueError(f"No actual receptor at requested coordinate; nearest {distance[index]}m")
    return index


def save_figure(fig, folder, stem, artifacts):
    for suffix in ("png", "pdf"):
        path = folder / f"{stem}.{suffix}"
        fig.savefig(path, dpi=300, bbox_inches="tight", facecolor="white")
        item = record(path)
        item.update({"figure_width_in":float(fig.get_figwidth()), "figure_height_in":float(fig.get_figheight()),
                     "render_dpi":300})
        if suffix == "png":
            from PIL import Image
            with Image.open(path) as preview:
                item.update({"pixel_width":preview.width, "pixel_height":preview.height})
        artifacts.append(item)
    plt.close(fig)


def plots(project, scenario, cases, output, artifacts):
    east, north = center(scenario)
    time_rows, wind_rows, transect_rows = [], [], []
    fig, axes = plt.subplots(1, 2, figsize=(18, 8.4))
    for rain, style in ((0., "--"), (1., "-")):
        case = next(item for item in cases if item["wind_speed_m_s"] == 2 and item["rain_mm_h"] == rain)
        index = receptor_index(case, east+1000, north)
        for metric, color in (("dry_deposition", COLORS[0]), ("wet_deposition", COLORS[4])):
            values = case["hourly"][metric].reshape((case["hours"], case["receptors"]))[:, index]
            label = f"{'Dry' if metric.startswith('dry') else 'Wet'} deposition; rain {rain:g} mm/h"
            axes[0].plot(np.arange(1, 25), values, color=color, ls=style, lw=2, label=label)
            axes[1].plot(np.arange(0, 25), np.r_[0., np.cumsum(values)], color=color, ls=style, lw=2, label=label)
            for hour, flux in enumerate(values, 1):
                time_rows.append((case["case"], rain, hour, metric, float(flux), float(values[:hour].sum())))
    axes[0].set(xlabel="Hour ending (local standard time)", ylabel="Deposition flux (µg m⁻² h⁻¹)", title="Steady hourly deposition flux")
    axes[1].set(xlabel="Elapsed modeled hours", ylabel="Accumulated deposition (µg m⁻²)", title="Accumulated deposition")
    for ax in axes:
        ax.grid(alpha=.2)
    axes[0].set_xlim(1, 24); axes[0].set_xticks([1, 6, 12, 18, 24])
    axes[1].set_xlim(0, 24); axes[1].set_xticks([0, 6, 12, 18, 24])
    axes[0].legend(fontsize=16, frameon=False)
    fig.suptitle("Controlled Clemson plume: 2 m s⁻¹, receptor 1 km east of source", fontsize=27)
    fig.text(.085, .025, "Constant forcing produces constant hourly flux; accumulated deposition increases with duration.\nDry deposition also occurs during rain. Controlled simulation; see the accompanying methods for assumptions.", fontsize=13)
    fig.subplots_adjust(left=.085, right=.98, bottom=.23, top=.80, wspace=.32)
    save_figure(fig, output, "deposition_flux_vs_time", artifacts)

    fig, axes = plt.subplots(1, 2, figsize=(18, 8.4), sharex=True)
    for rain, style in ((0., "--"), (1., "-")):
        selected = [item for item in cases if item["rain_mm_h"] == rain]
        for metric, color in (("dry_deposition", COLORS[0]), ("wet_deposition", COLORS[4])):
            values = []
            for case in selected:
                index = receptor_index(case, east+1000, north)
                flux = float(case["period"][metric][index]/case["hours"])
                values.append(flux)
                wind_rows.append((case["case"], case["wind_speed_m_s"], case["wind_group"], rain, metric, flux))
            ax = axes[0 if metric.startswith("dry") else 1]
            ax.plot([item["wind_speed_m_s"] for item in selected], values, "o", ls=style, color=color,
                    lw=1.8, label=f"Rain {rain:g} mm/h")
    for ax, name in zip(axes, ("Dry", "Wet")):
        ax.set(xlabel="Reference wind speed at 10 m (m s⁻¹)", ylabel="Deposition flux (µg m⁻² h⁻¹)", title=f"{name} deposition at 1 km east")
        ax.set_xticks([1, 2, 3.5, 5, 7]); ax.grid(alpha=.2); ax.legend(frameon=False, fontsize=17)
        ax.axvspan(.8, 2, color="#0072B2", alpha=.04); ax.axvspan(2, 5, color="#009E73", alpha=.04)
        ax.axvspan(5, 7.2, color="#D55E00", alpha=.04); ax.set_xlim(.8, 7.2)
    fig.suptitle("Controlled wind-speed sensitivity near Clemson", fontsize=27)
    fig.text(.085, .025, "Selected speeds: 1 (<2), 2/3.5/5 (2–5), and 7 (>5) m s⁻¹. Lines connect discrete scenarios.\nStability and rainfall are controlled; friction velocity changes consistently with wind speed. See accompanying methods.", fontsize=13)
    fig.subplots_adjust(left=.085, right=.98, bottom=.23, top=.80, wspace=.32)
    save_figure(fig, output, "deposition_flux_vs_wind_speed", artifacts)

    fig, axes = plt.subplots(1, 2, figsize=(18, 8.6), sharex=True)
    distances = (np.arange(100, 10001, 100) if cases[0]["receptors"] > 873
                 else np.r_[np.arange(100, 1001, 100), np.arange(2000, 10001, 1000)])
    for case, color in zip([item for item in cases if item["rain_mm_h"] == 1], COLORS):
        for metric, ax in zip(("dry_deposition", "wet_deposition"), axes):
            values = []
            for distance in distances:
                index = receptor_index(case, east+distance, north)
                flux = float(case["period"][metric][index]/case["hours"])
                values.append(flux)
                transect_rows.append((case["case"], case["wind_speed_m_s"], case["wind_group"], 1.,
                                      float(distance), metric, flux))
            ax.plot(distances/1000, np.where(np.asarray(values)>0, values, np.nan), "o-", color=color,
                    ms=3.5, lw=1.5, label=f"{case['wind_speed_m_s']:g} m/s ({case['wind_group']})")
    for ax, name in zip(axes, ("Dry", "Wet")):
        ax.set(xscale="log", yscale="log", xlabel="Projected east-axis distance from source (km)",
               ylabel="Deposition flux (µg m⁻² h⁻¹)", title=f"{name} deposition under rain (1 mm/h)")
        ax.grid(alpha=.2); ax.legend(frameon=False, fontsize=16)
    fig.suptitle("Deposition along actual downwind terrain receptors", fontsize=27)
    fig.text(.085, .025, "Each curve uses actual downwind terrain receptors under fixed wind and 1 mm/h rain.\nThese are controlled scenarios, not observed weather averages. Printed zeros are omitted from logarithmic axes.", fontsize=13)
    fig.subplots_adjust(left=.085, right=.98, bottom=.23, top=.80, wspace=.32)
    save_figure(fig, output, "deposition_flux_vs_distance", artifacts)

    baseline = next(item for item in cases if item["wind_speed_m_s"] == 2 and item["rain_mm_h"] == 1)
    xy = baseline["native"]["concentration"]["period"].numeric[:, :2]
    fig, axes = plt.subplots(3, 1, figsize=(18, 14.5), sharex=True, sharey=True)
    map_audit = {}
    for ax, metric in zip(axes, METRICS):
        values = baseline["period"][metric] / (baseline["hours"] if metric != "concentration" else 1)
        positives = values[values > 0]
        if not len(positives):
            norm = colors.Normalize(0, 1); shown = values
        else:
            vmin = max(float(positives.min()), float(positives.max()) * 1e-6)
            norm = colors.LogNorm(vmin, float(positives.max())); shown = np.ma.masked_where(values<=0, values)
        selected = ((xy[:, 0]-east>=-1000.1)&(xy[:, 0]-east<=10000.1)
                    &(np.abs(xy[:, 1]-north)<=1200.1))
        selected_xy, selected_values = xy[selected], values[selected]
        x_unique, y_unique = np.unique(selected_xy[:, 0]), np.unique(selected_xy[:, 1])
        regular = (len(selected_xy) == len(x_unique)*len(y_unique)
                   and np.allclose(np.diff(x_unique), 100, atol=.01)
                   and np.allclose(np.diff(y_unique), 100, atol=.01))
        if regular:
            field = np.full((len(y_unique), len(x_unique)), np.nan)
            field[np.searchsorted(y_unique, selected_xy[:, 1]),
                  np.searchsorted(x_unique, selected_xy[:, 0])] = selected_values
            artist = ax.pcolormesh((x_unique-east)/1000, (y_unique-north)/1000,
                                  np.ma.masked_where(field<=0, field), shading="nearest",
                                  cmap="viridis", norm=norm, rasterized=True)
            rendering = "Native 100m receptor-centered cells; no spatial interpolation"
        else:
            positive_selected = selected & (values > 0)
            artist = ax.scatter((xy[positive_selected, 0]-east)/1000, (xy[positive_selected, 1]-north)/1000,
                                c=values[positive_selected], cmap="viridis", norm=norm, marker="s", s=24,
                                linewidths=0, rasterized=True)
            rendering = "Native receptor squares; no spatial interpolation"
        ax.plot(0, 0, "*", color="red", markeredgecolor="white", ms=16)
        ax.annotate("Wind →", xy=(3, 1.03), xytext=(.4, 1.03), arrowprops={"arrowstyle":"->"}, fontsize=18)
        ax.set(aspect="equal", xlim=(-1.2, 10.3), ylim=(-1.25, 1.25))
        ax.set_title(LABELS[metric], fontsize=22)
        ax.set_ylabel("North of source (km)")
        fig.colorbar(artist, ax=ax, shrink=.75, pad=.025)
        map_audit[metric] = {"native_receptors": len(values), "positive": int(np.count_nonzero(values>0)),
                              "display_vmin": norm.vmin, "display_vmax": norm.vmax,
                              "interpolation": "None", "rendering":rendering,
                              "displayed_receptors":len(selected_values)}
    axes[-1].set_xlabel("East of source (km)")
    fig.suptitle("AERMOD steady-state plume near Clemson: 2 m s⁻¹, rain 1 mm h⁻¹", fontsize=27)
    fig.text(.08, .025, "Each square shows a computed receptor; no spatial interpolation. Wind FROM west (270°); hypothetical source ★.\nColors show positive values, clipped at 10⁻⁶ of each field maximum. See the accompanying methods for assumptions.", fontsize=13)
    fig.subplots_adjust(left=.08, right=.94, top=.9, bottom=.12, hspace=.42)
    save_figure(fig, output, "steady_state_plume_maps", artifacts)
    return time_rows, wind_rows, transect_rows, map_audit


def flatten(value, prefix=""):
    if isinstance(value, dict):
        for key, child in value.items():
            yield from flatten(child, prefix+"."+key if prefix else key)
    elif isinstance(value, list):
        for index, child in enumerate(value):
            yield from flatten(child, f"{prefix}[{index}]")
    else:
        yield prefix, value if value is not None else "null"


def artifact_records(value):
    if isinstance(value, dict):
        if isinstance(value.get("path"), str) and isinstance(value.get("sha256"), str):
            yield value
        for child in value.values():
            yield from artifact_records(child)
    elif isinstance(value, list):
        for child in value:
            yield from artifact_records(child)


def write_workbook(project, scenario, cases, output, figures, audit, csv_paths):
    path = output / "clemson_steady_state_inputs_outputs.xlsx"
    inventory, input_paths, report_paths = {}, set(), set()
    for metric_audit in audit["model_outputs"].values():
        execution = metric_audit["execution"]
        for item in execution["inputs"]:
            p = Path(item["path"]); input_paths.add(p); inventory[str(p)] = ("model_input", item)
        binary = execution["binary"]
        inventory[binary["path"]] = ("model_binary_identity_not_embedded", binary)
        for item in execution["completion_reports"]:
            p = Path(item["path"]); report_paths.add(p); inventory[str(p)] = ("native_report", item)
        for name in ("period", "hourly", "maximum"):
            item = metric_audit[name]; inventory[item["path"]] = ("native_"+name+"_output", item)
        item = execution["execution_record"]
        inventory[item["path"]] = ("execution_audit", item)
        if execution.get("manifest"):
            item = execution["manifest"]; inventory[item["path"]] = ("execution_manifest", item)
    input_paths.add(project / "scenario.json")
    for folder in (project/"aermap", project/"aermap_refined"):
        if not folder.exists():
            continue
        for candidate in folder.rglob("*"):
            if not candidate.is_file():
                continue
            if candidate.suffix.lower() in (".inp", ".rec", ".src"):
                input_paths.add(candidate); inventory[str(candidate)] = ("terrain_processing_input_or_include", record(candidate))
            elif (candidate.suffix.lower() in (".out", ".rpt", ".msg", ".sum", ".log")
                  or candidate.name.endswith((".stdout.txt", ".stderr.txt"))):
                report_paths.add(candidate); inventory[str(candidate)] = ("terrain_processing_native_report", record(candidate))
            elif candidate.suffix.lower() == ".json":
                inventory[str(candidate)] = ("terrain_processing_provenance", record(candidate))
                for item in artifact_records(json.loads(candidate.read_text())):
                    item_path = Path(item["path"])
                    if item_path.is_file():
                        if digest(item_path) != item["sha256"]:
                            raise ValueError(f"Terrain audit artifact is stale: {item_path}")
                        inventory.setdefault(str(item_path), ("terrain_audit_artifact_identity", item))
    workbook = xlsxwriter.Workbook(path, {"constant_memory": True, "strings_to_urls": False,
                                          "strings_to_formulas": False, "nan_inf_to_errors": False})
    header = workbook.add_format({"bold": True, "bg_color": "#16324F", "font_color": "white", "text_wrap": True})
    scientific = workbook.add_format({"num_format": "0.000000E+00"})
    wrap = workbook.add_format({"text_wrap": True, "valign": "top"})
    counts = {}
    def sheet(name, fields, rows, widths=None):
        ws = workbook.add_worksheet(name); ws.freeze_panes(1, 0); ws.set_default_row(15)
        ws.write_row(0, 0, fields, header); ws.set_row(0, 34)
        ws.set_column(0, len(fields)-1, 18)
        for column, field in enumerate(fields):
            if any(tag in field for tag in ("concentration_", "flux_", "accumulated_", "amount_")):
                ws.set_column(column, column, 20, scientific)
        if widths:
            for column, width in widths.items(): ws.set_column(column, column, width)
        count = 0
        for count, row in enumerate(rows, 1):
            if count >= 1048576:
                raise ValueError(f"Excel row limit exceeded on {name}")
            ws.write_row(count, 0, [x.item() if isinstance(x, np.generic) else x for x in row])
        ws.autofilter(0, 0, count, len(fields)-1); counts[name] = count
        return ws
    notes = [
        ("Purpose", "Controlled native AERMOD26135 steady-state plume scenarios near Clemson. This workbook contains every requested hourly/PERIOD receptor value, every model input text line, structured met/terrain inputs, and native completion reports."),
        ("Source", "Hypothetical 100 m × 100 m roadside patch; constant 10 g/day airborne tire-wear microplastic emission. Traffic, wear, and airborne fractions are explicit assumptions; not a measured Clemson inventory."),
        ("Reference year", "2024 is the latest nearby regional atmospheric-microplastics sampling year verified in the project research. Regional observations are context, not a complete annual Clemson dataset or calibration."),
        ("Model dates", "2024-07-15 hour-ending 01–24, Eastern Standard Time UTC−5 throughout; all cases use the same synthetic 24-hour controlled window. No annual observed-weather simulation is claimed."),
        ("Weather", "Each scenario repeats identical hourly forcing. Near-neutral stability, fixed west wind direction and other specified conditions; neutral-log-law friction velocity scales with wind speed. Rain 0 and 1 mm/h are paired controls."),
        ("Wind groups", "Discrete scenarios are 1 (<2), 2/3.5/5 (2–5), and 7 (>5) m/s. These are selected speeds, not measured bin averages. Boundaries 2 and 5 belong to 2–5."),
        ("Particles", "Monodisperse 5 µm numerical equivalent-sphere surrogate, density 1.234 g/cm3, mass fraction 1, effective χ = 1. No explicit fiber/film shape model."),
        ("Concentration", "Canonical units µg/m3. PERIOD is the valid-hour arithmetic mean. HourlyResults contains all native one-hour concentration values."),
        ("Deposition", "Canonical hourly amounts µg/m2. Each one-hour amount is numerically equal to that hour's mean flux µg/m2/h. PERIOD is accumulated deposition µg/m2; PeriodResults also divides by the actual 24 valid hours for mean flux."),
        ("Both processes", "Dry deposition can occur during rain; wet and dry depletion are both enabled consistently. The no-rain control has zero wet deposition by design."),
        ("Steady state", "Constant flux through time is expected. Accumulated deposit grows with duration. There is no simulated plume-front travel time, transient build-up, or particle trajectory."),
        ("Coordinates", "Full NAD83 / UTM zone 17N (EPSG:26917) meters. Terrain comes from actual USGS 3DEP, processed in four full-tile AERMAP shards and merged. Every receptor elevation, hill height, and flagpole field is retained."),
        ("Inputs", "ScenarioInputs has all JSON scalar values; SourceInputs and ParticleInputs repeat relevant structured fields. WeatherSurface/Profile hold every numeric SFC/PFL row. InputText preserves every model and terrain input deck, included source/receptor file, met file, and scenario line, with path and line number."),
        ("Outputs", "HourlyResults pivots the three native metric files onto matching time/receptor coordinates; no values are interpolated. PeriodResults contains every native PERIOD receptor result. Maximum1h contains all optional native maximum one-hour results and their separate dates. NativeReports preserves output, summary, and error text. FileInventory provides hashes and binary identities; raw files accompany the workbook."),
        ("Precision", "NativeEXP scientific output retains six digits after the decimal in the mantissa. CSV/Excel retain the native values without replacing zeros. A printed zero is not proof of absent environmental AMP."),
        ("Coverage", f"Inputs and outputs cover 10 meteorological cases × 3 metric runs × {cases[0]['receptors']} receptors × 24 hours. Binary executable bytes and raster pixels are identified by provenance rather than embedded in spreadsheet cells."),
        ("Plots", "Embedded PNG previews and accompanying native-data CSVs are included. FluxTime, WindSummary, and Transects provide the exact values used for those plots."),
    ]
    ws = sheet("README", ("Item", "Description"), notes, {0:24, 1:125}); ws.set_column(1, 1, 125, wrap)
    sheet("ScenarioInputs", ("Parameter", "Value"), flatten(scenario), {0:65, 1:95})
    sheet("SourceInputs", ("Parameter", "Value"), flatten(scenario.get("source", {})), {0:55, 1:95})
    particle = scenario.get("particle", scenario.get("particle_assumptions", {}))
    sheet("ParticleInputs", ("Parameter", "Value"), list(flatten(particle))+list(flatten(scenario.get("particle_cases", []))), {0:60, 1:95})
    scenario_rows = ((c["case"], c["wind_speed_m_s"], c["wind_group"], c["rain_mm_h"], c["hours"],
                      str(c["surface"].relative_to(project)), str(c["profile"].relative_to(project))) for c in cases)
    sheet("Scenarios", ("case", "wind_speed_m_s", "wind_group", "rain_mm_h", "hours", "surface_file", "profile_file"), scenario_rows, {0:28, 5:65, 6:65})
    sheet("WeatherSurface", ("case",)+SFC_FIELDS+("trailing_native_flags",), ((c["case"], *row) for c in cases for row in c["sfc_rows"]), {0:25})
    sheet("WeatherProfiles", ("case",)+PFL_FIELDS+("trailing_native_flags",), ((c["case"], *row) for c in cases for row in c["pfl_rows"]), {0:25})
    xy = cases[0]["native"]["concentration"]["period"].numeric
    sheet("TerrainReceptors", ("receptor_index", "x_m", "y_m", "terrain_elevation_m", "hill_height_m", "flagpole_height_m"),
          ((i+1, row[0], row[1], row[3], row[4], row[5]) for i, row in enumerate(xy)))
    sheet("HourlyResults", HOURLY_FIELDS, hourly_rows(cases), {0:25})
    sheet("PeriodResults", PERIOD_FIELDS, period_rows(cases), {0:25})
    sheet("Maximum1h", ("case", "wind_speed_m_s", "rain_mm_h", "x_m", "y_m", "terrain_elevation_m",
                        "hill_height_m", "flagpole_height_m", "source_group", "concentration_date_native",
                        "concentration_ug_m3", "dry_date_native", "dry_hour_amount_ug_m2", "wet_date_native",
                        "wet_hour_amount_ug_m2", "net_id", "native_averaging", "native_rank"), maximum_rows(cases), {0:25})
    for name, csv_path in csv_paths.items():
        with csv_path.open(newline="") as stream:
            reader = csv.reader(stream); fields = next(reader)
            rows = ([float(v) if re.fullmatch(r"[-+]?\d*\.?\d+(?:[eE][-+]?\d+)?", v) else v for v in row] for row in reader)
            sheet(name, fields, rows, {0:25})
    for name, paths in (("InputText", input_paths), ("NativeReports", report_paths)):
        def text_rows(paths):
            for file in sorted(paths):
                for number, line in enumerate(file.read_text(errors="strict").splitlines(), 1):
                    if len(line)>32700: raise ValueError(f"Excel cell length limit: {file}:{number}")
                    yield str(file.relative_to(project)), number, line
        sheet(name, ("file_relative_to_project", "line_number", "verbatim_line"), text_rows(paths), {0:70, 1:13, 2:145})
    sheet("FileInventory", ("role", "path", "sha256", "bytes"),
          ((role, path, item["sha256"], item.get("bytes", Path(path).stat().st_size)) for path, (role, item) in sorted(inventory.items())),
          {0:35, 1:105, 2:68, 3:18})
    research_rows = []
    for source in sorted((project / "research").glob("*")):
        if source.is_file() and source.suffix in (".md", ".txt", ".json", ".csv"):
            for number, line in enumerate(source.read_text().splitlines(), 1):
                research_rows.append((source.name, number, line))
    sheet("ResearchEvidence", ("file", "line_number", "verbatim_line"), research_rows, {0:45, 1:14, 2:145})
    for year in (2023, 2024):
        evidence = project/"research"/f"regional_observations_{year}.csv"
        if evidence.is_file():
            with evidence.open(newline="") as stream:
                reader = csv.reader(stream); fields = next(reader)
                values = ([float(v) if re.fullmatch(r"[-+]?\d*\.?\d+(?:[eE][-+]?\d+)?", v) else v for v in row] for row in reader)
                sheet(f"RegionalContext{year}", fields, values, {0:30})
    sheet("Validation", ("parameter", "value"), flatten({"native_counts":audit["native_output_counts"], "steady_aggregation_checks":audit["steady_checks"]}), {0:105, 1:80})
    run_rows = []
    for name, model in audit["model_outputs"].items():
        document = json.loads(Path(model["execution"]["execution_record"]["path"]).read_text())
        for key, value in flatten(document):
            run_rows.append((name, key, value))
    sheet("NativeRunAudit", ("case_and_metric", "parameter", "value"), run_rows, {0:35, 1:75, 2:110})
    terrain_rows = []
    for file in sorted((project/"aermap_refined").rglob("*.json")):
        for key, value in flatten(json.loads(file.read_text())):
            terrain_rows.append((str(file.relative_to(project)), key, value))
    sheet("TerrainAudit", ("file", "parameter", "value"), terrain_rows, {0:65, 1:75, 2:110})
    ws = workbook.add_worksheet("Plots"); ws.set_column(0, 20, 12)
    row = 1
    for image in sorted(figures.glob("*.png")):
        ws.write(row, 0, image.name, header); ws.insert_image(row+1, 0, str(image), {"x_scale":.28, "y_scale":.28})
        row += 34
    workbook.close()
    return path, counts, inventory


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args(argv)
    project = args.project.resolve(); output = project / "outputs"; figures = output / "figures"
    figures.mkdir(parents=True, exist_ok=True)
    plt.rcParams.update({"font.family":"DejaVu Sans", "font.size":18,
                         "axes.labelsize":22, "axes.titlesize":22, "xtick.labelsize":18,
                         "ytick.labelsize":18, "legend.fontsize":17,
                         "axes.spines.top":False, "axes.spines.right":False, "pdf.fonttype":42})
    provenance = {"created_utc":datetime.now(timezone.utc).isoformat(), "status":"in_progress",
                  "script":record(Path(__file__)), "scenario":record(project/"scenario.json"),
                  "verifier":record(Path(__file__).resolve().parents[2]/"scripts/result_provenance.py"),
                  "artifacts":[]}
    provenance["plot_style"] = {"figure_title_pt":27, "panel_title_pt":22, "axis_label_pt":22,
                                 "tick_label_pt":18, "legend_pt_range":[16,17], "footnote_pt":13,
                                 "figure_width_in":18, "minimum_text_size_pt":13}
    destination = output / "deliverables_provenance.json"
    try:
        scenario, cases, audit = load_all(project); provenance.update(audit)
        count_period = csv_table(output/"period_results.csv", PERIOD_FIELDS, period_rows(cases))
        print(f"PERIOD_CSV_READY {output/'period_results.csv'} {count_period}", flush=True)
        count_hourly = csv_table(output/"hourly_results.csv", HOURLY_FIELDS, hourly_rows(cases))
        print(f"HOURLY_CSV_READY {output/'hourly_results.csv'} {count_hourly}", flush=True)
        time, wind, transect, maps = plots(project, scenario, cases, figures, provenance["artifacts"])
        table_specs = {
            "FluxTime": (("case", "rain_mm_h", "hour_ending_lst", "metric", "flux_ug_m2_h", "accumulated_ug_m2"), time),
            "WindSummary": (("case", "wind_speed_m_s", "wind_group", "rain_mm_h", "metric", "flux_ug_m2_h"), wind),
            "Transects": (("case", "wind_speed_m_s", "wind_group", "rain_mm_h", "downwind_distance_m", "metric", "flux_ug_m2_h"), transect),
        }
        csv_paths = {}
        for name, (fields, rows) in table_specs.items():
            file = output / f"{name.lower()}.csv"; csv_table(file, fields, rows); csv_paths[name] = file
        workbook, sheets, inventory = write_workbook(project, scenario, cases, output, figures, audit, csv_paths)
        provenance["row_counts"] = {"hourly_results":count_hourly, "period_results":count_period, "workbook_sheets":sheets}
        provenance["map_rendering"] = maps
        for path in [workbook, output/"period_results.csv", output/"hourly_results.csv", *csv_paths.values()]:
            provenance["artifacts"].append(record(path))
        catalog = {"coordinate_system":"EPSG26917 NAD83/UTM17N", "concentration_unit":"ug/m3",
                   "deposition_hourly_flux_unit":"ug/m2/h", "deposition_period_unit":"ug/m2",
                   "period_results":record(output/"period_results.csv"),
                   "hourly_results":record(output/"hourly_results.csv"),
                   "cases":[{key:c[key] for key in ("case", "wind_speed_m_s", "wind_group", "rain_mm_h", "hours")} for c in cases]}
        (output/"results_catalog.json").write_text(json.dumps(catalog, indent=2)+"\n")
        provenance["artifacts"].append(record(output/"results_catalog.json"))
        provenance["status"] = "complete"
    except Exception as exc:
        provenance["status"] = "failed"; provenance["error"] = str(exc)
        destination.write_text(json.dumps(provenance, indent=2)+"\n")
        raise
    destination.write_text(json.dumps(provenance, indent=2)+"\n")
    print(json.dumps({"status":"complete", "workbook":str(workbook), "rows":provenance["row_counts"],
                      "artifacts":len(provenance["artifacts"])}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
