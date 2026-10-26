#!/usr/bin/env python3
"""Put verified AERMOD fields on a real, georeferenced topographic basemap.

This is a cartographic export of the existing u2_r1 scenario. It does not rerun
AERMOD, change numerical results, or construct a replacement Gaussian plume.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import math
import os
from pathlib import Path
import subprocess
import sys

os.environ.setdefault("MPLCONFIGDIR", "/workspace/.cloud-setup/amp-plots/matplotlib-cache")
import matplotlib
matplotlib.use("Agg")
from matplotlib import colors, pyplot as plt
import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent))
from build_kmz import artifact, read_table, verify_native


METRICS = {
    "concentration": {"title": "AERMOD concentration on the Clemson map", "label": "Concentration (µg m⁻³)"},
    "dry_deposition": {"title": "AERMOD dry deposition on the Clemson map", "label": "Dry deposition flux (µg m⁻² h⁻¹)"},
    "wet_deposition": {"title": "AERMOD wet deposition on the Clemson map", "label": "Wet deposition flux (µg m⁻² h⁻¹)"},
}


def extent_values(metadata: dict) -> tuple[float, float, float, float]:
    extent = metadata["extent"]
    if isinstance(extent, dict):
        values = tuple(float(extent[key]) for key in ("xmin", "ymin", "xmax", "ymax"))
        epsg = extent.get("spatialReference", {}).get("latestWkid", extent.get("spatialReference", {}).get("wkid"))
    else:
        values, epsg = tuple(map(float, extent)), None
    code = metadata.get("crs_epsg", metadata.get("epsg", epsg))
    if isinstance(code, str):
        code = code.removeprefix("EPSG:")
    if int(code) != 26917:
        raise ValueError("Basemap export must be genuinely georeferenced in EPSG:26917")
    if len(values) != 4 or not values[0] < values[2] or not values[1] < values[3]:
        raise ValueError("Invalid basemap extent")
    return values


def verify_basemap(metadata_path: Path) -> tuple[Path, dict, tuple]:
    metadata = json.loads(metadata_path.read_text())
    item = metadata["image"]
    image_path = Path(item["path"])
    if not image_path.is_absolute():
        image_path = metadata_path.parent / image_path
    actual = artifact(image_path)
    if actual["sha256"] != item["sha256"]:
        raise ValueError("Basemap image does not match its retrieval record")
    with Image.open(image_path) as image:
        image.verify()
    extent = extent_values(metadata)
    if not metadata.get("attribution"):
        raise ValueError("Real basemap attribution is required")
    return image_path, metadata, extent


def native_grid(group: dict, scenario: dict, metric: str) -> tuple[np.ndarray, np.ndarray, np.ndarray, dict]:
    center = scenario["center"]
    xy = group["xy"]
    dx, dy = xy[:, 0] - center["easting_m"], xy[:, 1] - center["northing_m"]
    selected = (dx >= -1000.01) & (dx <= 10000.01) & (np.abs(dy) <= 1000.01)
    grid = np.full((21, 111), np.nan)
    seen = set()
    for x, y, value in zip(dx[selected], dy[selected], group["values"][metric][selected]):
        ix, iy = round((x + 1000) / 100), round((y + 1000) / 100)
        if abs(x - (-1000 + ix * 100)) > .011 or abs(y - (-1000 + iy * 100)) > .011:
            raise ValueError("Refined-grid coordinate differs from its native 100 m grid")
        if (iy, ix) in seen:
            raise ValueError("Duplicate native refined-grid cell")
        seen.add((iy, ix))
        grid[iy, ix] = value
    if len(seen) != 2331 or np.any(~np.isfinite(grid)):
        raise ValueError("Complete 2,331-receptor fine plume grid is required")
    # Receptor-centered cells, clipped at the outer native receptor boundaries.
    # Every cell retains an actual computed receptor value: no interpolation.
    ex = np.clip(np.arange(-1050., 10051., 100.), -1000, 10000) / 1000
    ey = np.clip(np.arange(-1050., 1051., 100.), -1000, 1000) / 1000
    positive = grid[grid > 0]
    if not len(positive):
        raise ValueError("The requested baseline map field has no positive values")
    lo = max(float(positive.min()), float(positive.max()) * 1e-5)
    hi = float(positive.max())
    return ex, ey, grid, {
        "native_display_receptors": len(seen),
        "native_value_min": float(grid.min()), "native_value_max": hi,
        "display_log_min": lo, "display_log_max": hi,
        "display_method": "Actual native receptor-centered 100 m cells; no spatial interpolation; outer cells clipped at native grid boundary",
        "opacity": 0.48,
    }


def true_north_vector(scenario: dict) -> tuple[float, float]:
    center = scenario["center"]
    lon, lat = center["longitude"], center["latitude"]
    result = subprocess.run(
        ["gdaltransform", "-s_srs", "EPSG:4326", "-t_srs", "EPSG:26917"],
        input=f"{lon} {lat}\n{lon} {lat+.01}\n", text=True, capture_output=True, check=True)
    points = np.array([[float(v) for v in line.split()[:2]] for line in result.stdout.splitlines()])
    vector = points[1] - points[0]
    vector /= np.linalg.norm(vector)
    return float(vector[0]), float(vector[1])


def add_context(ax, scenario: dict, bounds_km: tuple, north_vector: tuple):
    xmin, ymin, xmax, ymax = bounds_km
    ax.plot(0, 0, marker="*", ms=21, color="#e31a1c", mec="white", mew=1.5, zorder=8)
    ax.annotate("Hypothetical source", xy=(0, 0), xytext=(.30, -1.43),
                fontsize=17, color="#a11010", fontweight="bold", zorder=9,
                bbox={"facecolor": "white", "edgecolor": "none", "alpha": .92, "pad": 3},
                arrowprops={"arrowstyle": "->", "color": "#a11010", "lw": 1.7})
    # The wind input is expressed on the projected model grid.
    ax.annotate("Wind 2 m s⁻¹", xy=(5.1, 1.40), xytext=(2.2, 1.40),
                fontsize=18, ha="center", va="center", zorder=9,
                bbox={"facecolor": "white", "edgecolor": "none", "alpha": .88, "pad": 3},
                arrowprops={"arrowstyle": "-|>", "color": "#262626", "lw": 2.5})
    # A 2 km projected scale bar. It is independent of the model concentration.
    sx, sy = xmax - 2.65, ymin + .42
    ax.plot([sx, sx + 2], [sy, sy], color="white", lw=9, solid_capstyle="butt", zorder=9)
    ax.plot([sx, sx + 2], [sy, sy], color="#222222", lw=4, solid_capstyle="butt", zorder=10)
    for x in (sx, sx + 1, sx + 2):
        ax.plot([x, x], [sy-.06, sy+.06], color="#222222", lw=2, zorder=10)
    ax.text(sx + 1, sy + .11, "2 km", ha="center", va="bottom", fontsize=16, zorder=10,
            bbox={"facecolor": "white", "edgecolor": "none", "alpha": .9, "pad": 2})
    nx, ny = xmax - .65, ymax - 1.15
    vx, vy = north_vector
    ax.annotate("N", xy=(nx + vx*.58, ny + vy*.58), xytext=(nx, ny-.12),
                fontsize=19, fontweight="bold", ha="center", va="top", zorder=10,
                arrowprops={"arrowstyle": "-|>", "lw": 2.2, "color": "#222222"},
                bbox={"facecolor": "white", "edgecolor": "none", "alpha": .9, "pad": 2})


def render(project: Path, output: Path, metadata_path: Path) -> dict:
    source = project / "scenario.json"
    scenario = json.loads(source.read_text())
    image_path, basemap, extent = verify_basemap(metadata_path)
    groups = read_table(project / "outputs/period_results.csv")
    executions = verify_native(project, {"u2_r1": groups["u2_r1"]})
    group = groups["u2_r1"]
    if group["wind_speed_m_s"] != 2 or group["rain_mm_h"] != 1:
        raise ValueError("Requested baseline differs from 2 m/s and 1 mm/h rain")
    center = scenario["center"]
    bounds_km = tuple((extent[i] - center["easting_m" if i % 2 == 0 else "northing_m"]) / 1000 for i in range(4))
    xmin, ymin, xmax, ymax = bounds_km
    if xmin > -1 or xmax < 10 or ymin > -1 or ymax < 1:
        raise ValueError("Basemap does not cover the full refined plume display")
    # Transparent seam/nodata pixels in the georeferenced mosaic stay white;
    # dropping alpha directly would incorrectly turn those few pixels black.
    source_image = Image.open(image_path).convert("RGBA")
    white = Image.new("RGBA", source_image.size, (255, 255, 255, 255))
    image = np.asarray(Image.alpha_composite(white, source_image).convert("RGB"))
    north_vector = true_north_vector(scenario)
    plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 18,
                         "axes.labelsize": 22, "xtick.labelsize": 18, "ytick.labelsize": 18,
                         "pdf.fonttype": 42, "ps.fonttype": 42})
    artifacts, fields = [], {}
    for metric, labels in METRICS.items():
        ex, ey, grid, audit = native_grid(group, scenario, metric)
        fig, ax = plt.subplots(figsize=(18, 9.6))
        fig.subplots_adjust(left=.09, right=.86, bottom=.24, top=.84)
        ax.imshow(image, extent=(xmin, xmax, ymin, ymax), origin="upper", aspect="equal", zorder=0)
        cmap = plt.get_cmap("plasma").copy()
        cmap.set_bad((0, 0, 0, 0))
        norm = colors.LogNorm(audit["display_log_min"], audit["display_log_max"], clip=True)
        visible = np.ma.masked_where(grid <= 0, grid)
        field = ax.pcolormesh(ex, ey, visible, cmap=cmap, norm=norm, alpha=audit["opacity"],
                              shading="flat", rasterized=True, zorder=2)
        # Fine outlines separate the modeled field from the map without
        # claiming a physical threshold-defined edge of transport.
        xcenters = np.arange(-1000, 10001, 100) / 1000
        ycenters = np.arange(-1000, 1001, 100) / 1000
        contour_levels = ([1e-4, 1e-3, 1e-2] if metric == "concentration" else
                          [10. ** exponent for exponent in range(-5, 2)])
        contour_levels = [value for value in contour_levels if grid.min() < value < grid.max()]
        contours = ax.contour(xcenters, ycenters, grid, levels=contour_levels,
                              colors="#3e155c", linewidths=.8, alpha=.8, zorder=3)
        ax.clabel(contours, fmt=lambda value: f"{value:g}", fontsize=14, inline=True)
        add_context(ax, scenario, bounds_km, north_vector)
        distances = np.hypot(group["xy"][:, 0] - center["easting_m"] - 1000,
                             group["xy"][:, 1] - center["northing_m"])
        anchor = int(distances.argmin())
        if distances[anchor] > .1:
            raise ValueError("Actual 1 km downwind receptor is missing")
        anchor_value = float(group["values"][metric][anchor])
        exponent = math.floor(math.log10(anchor_value))
        coefficient = anchor_value / 10 ** exponent
        anchor_unit = "µg m⁻³" if metric == "concentration" else "µg m⁻² h⁻¹"
        ax.plot(1, 0, marker="o", ms=6, color="white", mec="#252525", zorder=8)
        ax.annotate(f"1 km: {coefficient:.2f} × 10$^{{{exponent}}}$ {anchor_unit}",
                    xy=(1, 0), xytext=(4.0, -1.43), fontsize=16, zorder=9,
                    bbox={"facecolor": "white", "edgecolor": "none", "alpha": .94, "pad": 3},
                    arrowprops={"arrowstyle": "->", "color": "#252525", "lw": 1.3})
        audit["one_km_native_anchor"] = {"xy_m": group["xy"][anchor].tolist(),
                                          "value": anchor_value, "unit": anchor_unit}
        audit["contour_levels"] = contour_levels
        ax.set(xlim=(xmin, xmax), ylim=(ymin, ymax), xlabel="Projected distance east of source (km)",
               ylabel="Projected distance north of source (km)")
        ax.set_xticks(np.arange(0, 10.1, 2))
        ax.set_yticks(np.arange(math.ceil(ymin), math.floor(ymax)+.1, 1))
        cax = fig.add_axes([.89, .315, .021, .44])
        colorbar = fig.colorbar(field, cax=cax)
        colorbar.ax.tick_params(labelsize=18)
        colorbar.set_label(labels["label"], fontsize=22, labelpad=13)
        fig.suptitle(labels["title"] + "\n2 m s⁻¹ west wind · rain 1 mm h⁻¹ · fixed steady-state conditions", fontsize=27, y=.96)
        fig.text(.09, .155,
                 "Hypothetical source: 10 g/day; 5 µm spherical particles. Source: 34.680° N, 82.840° W.\n"
                 "Semi-transparent native 100 m cells; contours use legend units. Overlay edges are display limits.\n"
                 "2024 is a regional-data reference; forcing is synthetic. No ambient microplastic background is added.", fontsize=13)
        attribution = str(basemap["attribution"])
        import textwrap
        if not attribution.lower().startswith("basemap:"):
            attribution = "Basemap: " + attribution
        fig.text(.09, .075, "\n".join(textwrap.wrap(attribution, width=145)), fontsize=12)
        for suffix in ("png", "pdf"):
            path = output / f"clemson_aermod_{metric}_on_map.{suffix}"
            fig.savefig(path, dpi=300, bbox_inches="tight", facecolor="white")
            artifacts.append(artifact(path))
        plt.close(fig)
        fields[metric] = audit
    return {
        "created_utc": datetime.now(timezone.utc).isoformat(), "status": "complete",
        "scenario": artifact(source), "period_table": artifact(project / "outputs/period_results.csv"),
        "script": artifact(Path(__file__).resolve()),
        "dependencies": [artifact(Path(__file__).with_name("build_kmz.py")),
                         artifact(project.parent / "scripts/result_provenance.py")],
        "basemap_metadata": artifact(metadata_path), "basemap_image": artifact(image_path),
        "basemap_source": basemap, "native_execution_verification": executions,
        "case": "u2_r1", "model_crs": "EPSG:26917", "basemap_extent_m": list(extent),
        "north_arrow": "True geographic north obtained by GDAL-transforming a northward geographic vector",
        "scale_bar": "2 km in the model UTM projection",
        "fields": fields, "artifacts": artifacts,
        "limitations": "The source/weather are illustrative. Native results are unchanged. Transparency and receptor cells are cartographic display choices; the basemap is geographic context, not model calibration.",
        "font_sizes_pt": {"titles": 27, "axes": 22, "ticks": 18, "map_annotations": "16–19", "notes": "12–13"},
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--basemap-json", type=Path)
    args = parser.parse_args()
    project = args.project.resolve()
    metadata_path = (args.basemap_json.resolve() if args.basemap_json else
                     project / "map_context/basemap/basemap_metadata.json")
    output = project / "map_context/outputs"
    output.mkdir(parents=True, exist_ok=True)
    record = output / "map_overlay_provenance.json"
    try:
        result = render(project, output, metadata_path)
    except Exception as exc:
        record.write_text(json.dumps({"status": "failed", "error": str(exc)}, indent=2)+"\n")
        raise
    record.write_text(json.dumps(result, indent=2, allow_nan=False)+"\n")
    print(json.dumps({"status": "complete", "artifacts": len(result["artifacts"]), "provenance": str(record)}, indent=2))


if __name__ == "__main__":
    main()
