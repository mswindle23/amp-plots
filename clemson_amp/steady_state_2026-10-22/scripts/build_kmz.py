#!/usr/bin/env python3
"""Build self-contained, georeferenced KMZs from verified native AERMOD fields.

Run after build_deliverables.py has written outputs/period_results.csv. Native
receptor values remain available as point layers. Display overlays linearly
interpolate the computed receptor values and are warped from NAD83 / UTM17N
to a regular WGS84 grid with GDAL; they are not Gaussian plume calculations.
"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
import csv
from datetime import datetime, timezone
import hashlib
from importlib.metadata import version
import json
import math
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
import zipfile

import os
os.environ.setdefault("MPLCONFIGDIR", "/workspace/.cloud-setup/amp-plots/matplotlib-cache")
os.environ.setdefault("XDG_CACHE_HOME", "/tmp/clemson-kmz-font-cache")
Path(os.environ["XDG_CACHE_HOME"]).mkdir(parents=True, exist_ok=True)
import matplotlib
matplotlib.use("Agg")
from matplotlib import colors, pyplot as plt
from PIL import Image, ImageDraw
import numpy as np
from scipy.interpolate import LinearNDInterpolator


KML_NS = "http://www.opengis.net/kml/2.2"
ET.register_namespace("", KML_NS)
METRICS = {
    "concentration": {"column": "concentration_ug_m3", "native_column": "concentration_ug_m3",
                      "title": "Steady concentration", "unit": "µg/m³", "native_label": "CONC"},
    "dry_deposition": {"column": "dry_flux_ug_m2_h", "native_column": "dry_accumulated_ug_m2",
                       "title": "Dry deposition flux", "unit": "µg/m²/h", "native_label": "DRY"},
    "wet_deposition": {"column": "wet_flux_ug_m2_h", "native_column": "wet_accumulated_ug_m2",
                       "title": "Wet deposition flux", "unit": "µg/m²/h", "native_label": "WET"},
}


def sha256(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def artifact(path: Path) -> dict:
    return {"path": str(path.resolve()), "sha256": sha256(path), "bytes": path.stat().st_size}


def command(arguments: list[str], *, stdin: str | None = None) -> str:
    return subprocess.run(arguments, input=stdin, text=True, capture_output=True,
                          check=True).stdout


def transform(coordinates: np.ndarray) -> np.ndarray:
    """Transform actual coordinates through GDAL/PROJ, never an affine shortcut."""
    data = "".join(f"{x:.12f} {y:.12f}\n" for x, y in coordinates)
    transformed = command(["gdaltransform", "-s_srs", "EPSG:26917", "-t_srs", "EPSG:4326"], stdin=data)
    result = np.array([[float(v) for v in line.split()[:2]]
                       for line in transformed.splitlines() if line.strip()])
    if result.shape != coordinates.shape or not np.all(np.isfinite(result)):
        raise ValueError("GDAL returned incomplete/nonfinite geographic coordinates")
    if np.any((result[:, 0] < -84) | (result[:, 0] > -81)
              | (result[:, 1] < 33) | (result[:, 1] > 36)):
        raise ValueError("Transformed receptor coordinates are outside the Clemson region")
    return result


def read_table(path: Path) -> dict[str, dict]:
    groups: dict[str, dict] = {}
    with path.open(newline="", encoding="utf-8") as stream:
        for row in csv.DictReader(stream):
            name = row["case"]
            group = groups.setdefault(name, {"rows": [], "wind_speed_m_s": float(row["wind_speed_m_s"]),
                                             "rain_mm_h": float(row["rain_mm_h"])})
            if (group["wind_speed_m_s"] != float(row["wind_speed_m_s"])
                    or group["rain_mm_h"] != float(row["rain_mm_h"])):
                raise ValueError(f"Inconsistent case forcing in {name}")
            group["rows"].append(row)
    if not groups:
        raise ValueError("No native-result rows in period table")
    reference = None
    for name, group in groups.items():
        group["rows"].sort(key=lambda row: (float(row["x_m"]), float(row["y_m"])))
        group["xy"] = np.array([[float(row["x_m"]), float(row["y_m"])] for row in group["rows"]])
        if len(np.unique(group["xy"], axis=0)) != len(group["xy"]):
            raise ValueError(f"Duplicate receptor in {name}")
        if reference is None:
            reference = group["xy"]
        elif not np.array_equal(reference, group["xy"]):
            raise ValueError("Receptor coordinates differ between cases")
        group["values"] = {metric: np.array([float(row[info["column"]]) for row in group["rows"]])
                           for metric, info in METRICS.items()}
        if any(np.any(~np.isfinite(values)) or np.any(values < 0) for values in group["values"].values()):
            raise ValueError(f"Nonfinite or negative native values in {name}")
    return groups


def verify_native(project: Path, groups: dict) -> list[dict]:
    """Require successful native audits and exact table/native PERIOD bindings."""
    sys.path.insert(0, str(project.parent / "scripts"))
    from result_provenance import verify_model_result
    checked = []
    for name, group in groups.items():
        for metric, info in METRICS.items():
            native = project / "aermod" / name / metric / "annual.plt"
            execution = verify_model_result(project, native)
            text = native.read_text(encoding="ascii")
            header = next((line for line in text.splitlines() if "ZELEV" in line), "")
            if info["native_label"] not in header.split("ZELEV")[0]:
                raise ValueError(f"Incorrect native metric in {native}")
            records = []
            for line in text.splitlines():
                if not line.strip() or line.lstrip().startswith("*"):
                    continue
                fields = line.split()
                if len(fields) < 9 or fields[6] != "PERIOD":
                    raise ValueError(f"Not a single-metric PERIOD record: {native}")
                records.append((float(fields[0]), float(fields[1]), float(fields[2]), int(fields[8])))
            records.sort(key=lambda row: row[:2])
            if not np.array_equal(np.array([row[:2] for row in records]), group["xy"]):
                raise ValueError(f"Table/native coordinates differ for {name}/{metric}")
            if len({row[3] for row in records}) != 1 or records[0][3] != 24:
                raise ValueError("KMZs require the verified 24-hour controlled runs")
            accumulated = np.array([row[2] for row in records])
            column = np.array([float(row[info["native_column"]]) for row in group["rows"]])
            if not np.array_equal(accumulated, column):
                raise ValueError(f"Table/native result mismatch for {name}/{metric}")
            expected = accumulated if metric == "concentration" else accumulated / 24
            if not np.allclose(expected, group["values"][metric], rtol=2e-6, atol=1e-15):
                raise ValueError(f"Incorrect accumulation-to-flux conversion for {name}/{metric}")
            deck = (native.parent / "aermod.inp").read_text()
            required = r"SO\s+CONCUNIT\s+([\d.Ee+\-]+)" if metric == "concentration" else r"SO\s+DEPOUNIT\s+([\d.Ee+\-]+)"
            match = re.search(required, deck, re.I)
            if not match or not math.isclose(float(match.group(1)), 1e6 if metric == "concentration" else 3.6e9):
                raise ValueError("Native unit factor differs from the documented KMZ unit")
            checked.append(execution)
    return checked


def e(parent: ET.Element, tag: str, text=None, **attributes) -> ET.Element:
    node = ET.SubElement(parent, f"{{{KML_NS}}}{tag}", attributes)
    if text is not None:
        node.text = str(text)
    return node


def normalize(groups: dict, metric: str):
    values = np.concatenate([group["values"][metric] for group in groups.values()])
    positive = values[values > 0]
    if not len(positive):
        return colors.Normalize(0, 1), {"scale": "all_zero", "min": 0, "max": 0}
    lo, hi = float(positive.min()), float(positive.max())
    if lo == hi:
        lo, hi = lo / math.sqrt(10), hi * math.sqrt(10)
    return colors.LogNorm(lo, hi), {"scale": "logarithmic, shared across wind/rain cases", "min": lo, "max": hi}


def legend_png(path: Path, metric: str, norm, scale: dict) -> None:
    fig = plt.figure(figsize=(7.5, 2.2), dpi=150)
    fig.patch.set_facecolor((1, 1, 1, .93))
    ax = fig.add_axes([.08, .48, .84, .16])
    if scale["scale"] == "all_zero":
        ax.axis("off")
        fig.text(.08, .51, "All native results zero", fontsize=16)
    else:
        fig.colorbar(plt.cm.ScalarMappable(norm=norm, cmap="viridis"), cax=ax, orientation="horizontal")
        ax.tick_params(labelsize=14)
    fig.text(.08, .81, f"{METRICS[metric]['title']} ({METRICS[metric]['unit']})", fontsize=18)
    fig.text(.08, .08, "Display interpolation of native receptors; shared positive log scale.\n"
             "Transparent: zero/no coverage. Point layers retain actual values.", fontsize=12)
    fig.savefig(path, dpi=150)
    plt.close(fig)


def overlay_png(work: Path, name: str, metric: str, xy: np.ndarray, values: np.ndarray,
                norm, bounds: tuple[float, float, float, float], resolution: float) -> tuple[Path, dict]:
    west, east, south, north = bounds
    nx = math.ceil((east - west) / resolution)
    ny = math.ceil((north - south) / resolution)
    x = west + (np.arange(nx) + .5) * (east - west) / nx
    y = north - (np.arange(ny) + .5) * (north - south) / ny
    gx, gy = np.meshgrid(x, y)
    image_values = LinearNDInterpolator(xy, values, fill_value=np.nan)(gx, gy)
    rgba = np.zeros((ny, nx, 4), dtype=np.uint8)
    positive = np.isfinite(image_values) & (image_values > 0)
    rgba[positive] = (plt.get_cmap("viridis")(norm(image_values[positive])) * 255).astype(np.uint8)
    rgba[..., 3][positive] = 195
    png = work / f"{name}_{metric}_utm.png"
    Image.fromarray(rgba).save(png)
    projected = work / f"{name}_{metric}_utm.tif"
    geographic = work / f"{name}_{metric}_wgs84.tif"
    target = work / f"{name}_{metric}.png"
    command(["gdal_translate", "-q", "-of", "GTiff", "-a_srs", "EPSG:26917", "-a_ullr",
             str(west), str(north), str(east), str(south), str(png), str(projected)])
    command(["gdalwarp", "-q", "-overwrite", "-s_srs", "EPSG:26917", "-t_srs", "EPSG:4326",
             "-srcalpha", "-dstalpha", "-r", "near", str(projected), str(geographic)])
    command(["gdal_translate", "-q", "-of", "PNG", str(geographic), str(target)])
    info = json.loads(command(["gdalinfo", "-json", str(geographic)]))
    gt = info["geoTransform"]
    width, height = info["size"]
    geo_bounds = {"west": gt[0], "east": gt[0] + width * gt[1],
                  "north": gt[3], "south": gt[3] + height * gt[5]}
    if not geo_bounds["west"] < geo_bounds["east"] or not geo_bounds["south"] < geo_bounds["north"]:
        raise ValueError("Invalid GDAL-warped geographic bounds")
    return target, {"projected_display_bounds_m": list(bounds), "interpolation": "linear native receptor values; outside hull masked",
                    "display_pixel_size_m_approx": resolution, "geographic_bounds": geo_bounds,
                    "image_dimensions_px": [width, height]}


def source_and_wind(document: ET.Element, scenario: dict) -> None:
    center = scenario["center"]
    source = scenario["source"]
    particle = scenario["particle"]
    x, y = float(center["easting_m"]), float(center["northing_m"])
    half_x, half_y = float(source["x_length_m"]) / 2, float(source["y_length_m"]) / 2
    vertices = transform(np.array([[x-half_x, y-half_y], [x+half_x, y-half_y],
                                   [x+half_x, y+half_y], [x-half_x, y+half_y], [x-half_x, y-half_y]]))
    placemark = e(document, "Placemark")
    e(placemark, "name", "Hypothetical continuous AMP source (100 × 100 m)")
    e(placemark, "description", "Hypothetical vehicle-related source; emissions are assumed, not measured. "
      f"Q={float(source['total_emission_g_s']):.12g} g/s; "
      f"equivalent-sphere diameter={float(particle['diameter_um']):g} µm, "
      f"density={float(particle['density_g_cm3']):g} g/cm³, chi=1. "
      f"Controlled simulation date={scenario['simulation_date']}; 24 identical hourly inputs. "
      "See workbook and methods for complete assumptions; the calendar date does not identify observed constant weather.")
    style = e(placemark, "Style")
    line = e(style, "LineStyle"); e(line, "color", "ff0000ff"); e(line, "width", 2)
    poly_style = e(style, "PolyStyle"); e(poly_style, "color", "550000ff")
    polygon = e(placemark, "Polygon"); e(polygon, "tessellate", 1)
    ring = e(e(polygon, "outerBoundaryIs"), "LinearRing")
    e(ring, "coordinates", " ".join(f"{lon:.10f},{lat:.10f},0" for lon, lat in vertices))
    arrow_xy = np.array([[x-600, y-1400], [x+600, y-1400], [x+400, y-1300],
                          [x+600, y-1400], [x+400, y-1500]])
    arrow = transform(arrow_xy)
    marker = e(document, "Placemark")
    e(marker, "name", "Wind FROM west (270°); transport toward east")
    e(marker, "description", "Orientation arrow only; not a modeled particle trajectory.")
    style = e(marker, "Style"); line = e(style, "LineStyle")
    e(line, "color", "ff0000ff"); e(line, "width", 3)
    geometry = e(marker, "LineString"); e(geometry, "tessellate", 1)
    e(geometry, "coordinates", " ".join(f"{lon:.10f},{lat:.10f},0" for lon, lat in arrow))


def add_layer(folder: ET.Element, case: str, group: dict, metric: str, ll: np.ndarray,
              image_info: dict, norm, *, visible: bool) -> None:
    info = METRICS[metric]
    field = e(folder, "Folder"); e(field, "name", f"{info['title']} ({info['unit']})")
    e(field, "visibility", int(visible))
    description = (f"Actual native AERMOD26135 results for {case}. Wind {group['wind_speed_m_s']:g} m/s FROM 270°; "
                   f"precipitation {group['rain_mm_h']:g} mm/h. Constant controlled forcing for 24 modeled hours. "
                   "Overlay: linear display interpolation of native receptor values over the refined plume grid; "
                   "it is not an independently calculated Gaussian plume. Native point values are available below. "
                   "Deposition units are µg/m²/h, obtained from validated 24-hour accumulation / 24; "
                   "this is not deposition velocity. Terrain and hourly steady-state assumptions are described in the workbook.")
    e(field, "description", description)
    overlay = e(field, "GroundOverlay"); e(overlay, "name", "Interpolated display — computed plume grid")
    e(overlay, "visibility", int(visible)); e(overlay, "color", "ffffffff")
    e(e(overlay, "Icon"), "href", f"images/{case}_{metric}.png")
    box = e(overlay, "LatLonBox")
    for key in ("north", "south", "east", "west"):
        e(box, key, f"{image_info['geographic_bounds'][key]:.12f}")
    e(box, "rotation", 0)
    legend = e(field, "ScreenOverlay"); e(legend, "name", "Units and shared color scale")
    e(e(legend, "Icon"), "href", f"images/legend_{metric}.png")
    e(legend, "overlayXY", x="0", y="1", xunits="fraction", yunits="fraction")
    e(legend, "screenXY", x="0.01", y="0.98", xunits="fraction", yunits="fraction")
    # Fractional width fits the viewer; y=0 preserves the embedded PNG aspect.
    e(legend, "size", x="0.70", y="0", xunits="fraction", yunits="pixels")
    points = e(field, "Folder"); e(points, "name", "Actual native receptor values (click for values)")
    e(points, "visibility", 0)
    values = group["values"][metric]
    positive = values > 0
    color_indices = np.zeros(len(values), dtype=int)
    color_indices[positive] = np.clip((norm(values[positive])*47).astype(int), 0, 47)
    for index, (row, coord, value, color_index) in enumerate(zip(group["rows"], ll, values, color_indices), 1):
        mark = e(points, "Placemark"); e(mark, "name", f"Receptor {index}: {value:.7g} {info['unit']}")
        e(mark, "description", f"{case}; native UTM E={row['x_m']} m, N={row['y_m']} m; "
          f"{info['title']}={value:.12g} {info['unit']}. "
          "Native calculated receptor value; displayed overlay interpolation is not used for this point.")
        e(mark, "styleUrl", "#zero" if value == 0 else f"#point{color_index}")
        point = e(mark, "Point"); e(point, "altitudeMode", "clampToGround")
        e(point, "coordinates", f"{coord[0]:.10f},{coord[1]:.10f},0")


def write_kmz(path: Path, cases: list[str], metrics: list[str], groups: dict, scenario: dict,
              layers: dict, legends: dict, norms: dict, ll: np.ndarray, work: Path) -> dict:
    root = ET.Element(f"{{{KML_NS}}}kml")
    doc = e(root, "Document"); e(doc, "name", path.stem)
    e(doc, "description", "Controlled steady-state microplastic-surrogate AERMOD scenarios near Clemson, SC. "
      "Synthetic constant meteorology; no measured local emission inventory. The study reference year is a calendar/data label, "
      "not an observed constant-wind year. Native receptor values, display interpolation and units are identified per layer. "
      "Self-contained KMZ: no external images or map requests are required for the modeled overlay.")
    view = e(doc, "LookAt")
    center = transform(np.array([[float(scenario["center"]["easting_m"])+4000,
                                 float(scenario["center"]["northing_m"])]]))[0]
    e(view, "longitude", center[0]); e(view, "latitude", center[1])
    e(view, "heading", 0); e(view, "tilt", 0); e(view, "range", 19000)
    for index in range(48):
        rgb = (np.array(plt.get_cmap("viridis")(index/47)[:3])*255).astype(int)
        style = e(doc, "Style", id=f"point{index}")
        icon = e(style, "IconStyle")
        e(icon, "color", f"ff{rgb[2]:02x}{rgb[1]:02x}{rgb[0]:02x}")
        e(icon, "scale", .45)
        e(e(icon, "Icon"), "href", "images/receptor.png")
        e(e(style, "LabelStyle"), "scale", 0)
    style = e(doc, "Style", id="zero"); icon = e(style, "IconStyle")
    e(icon, "color", "ff888888"); e(icon, "scale", .35)
    e(e(icon, "Icon"), "href", "images/receptor.png"); e(e(style, "LabelStyle"), "scale", 0)
    source_and_wind(doc, scenario)
    baseline = "u2_r1"
    for case in cases:
        group = groups[case]
        folder = e(doc, "Folder")
        e(folder, "name", f"{case}: wind {group['wind_speed_m_s']:g} m/s; rain {group['rain_mm_h']:g} mm/h")
        active = len(cases) == 1 or case == baseline
        e(folder, "visibility", int(active))
        for metric in metrics:
            add_layer(folder, case, group, metric, ll, layers[f"{case}/{metric}"][1], norms[metric],
                      visible=len(metrics) == 1 or metric == "concentration")
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        archive.writestr("doc.kml", ET.tostring(root, encoding="utf-8", xml_declaration=True))
        archive.write(work/"receptor.png", "images/receptor.png")
        for metric in metrics:
            archive.write(legends[metric], f"images/legend_{metric}.png")
        for case in cases:
            for metric in metrics:
                archive.write(layers[f"{case}/{metric}"][0], f"images/{case}_{metric}.png")
    return validate_kmz(path)


def validate_kmz(path: Path) -> dict:
    gis_open = command(["ogrinfo", "-ro", "-so", str(path)])
    if "successful" not in gis_open or "LIBKML" not in gis_open:
        raise ValueError("GDAL LIBKML did not successfully open the direct KMZ")
    with zipfile.ZipFile(path) as archive:
        if archive.testzip() is not None:
            raise ValueError(f"KMZ CRC failure: {path}")
        document = ET.fromstring(archive.read("doc.kml"))
        ns = {"k": KML_NS}
        hrefs = [node.text for node in document.findall(".//k:href", ns)]
        for href in hrefs:
            if not href or "://" in href or href not in archive.namelist():
                raise ValueError(f"KMZ has external/unresolved resource: {href}")
        style_ids = {node.attrib["id"] for node in document.findall(".//k:Style", ns)
                     if "id" in node.attrib}
        for style_url in document.findall(".//k:styleUrl", ns):
            if not style_url.text or not style_url.text.startswith("#") or style_url.text[1:] not in style_ids:
                raise ValueError("KMZ has an unresolved point style")
        count = 0
        for coordinates in document.findall(".//k:coordinates", ns):
            for token in (coordinates.text or "").split():
                lon, lat, *_ = map(float, token.split(","))
                if not -84 < lon < -81 or not 33 < lat < 36:
                    raise ValueError("KMZ coordinates outside Clemson region")
                count += 1
        for name in archive.namelist():
            if name.endswith(".png"):
                import io
                with Image.open(io.BytesIO(archive.read(name))) as image:
                    image.verify()
        return {**artifact(path), "validation": "GDAL LIBKML direct KMZ open, ZIP CRC, KML XML, local resource/style resolution, image decoding and coordinate bounds passed",
                "embedded_resources": len(archive.namelist())-1, "coordinate_vertices": count,
                "ground_overlays": len(document.findall(".//k:GroundOverlay", ns)),
                "screen_legends": len(document.findall(".//k:ScreenOverlay", ns))}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--table", type=Path, help="Default PROJECT/outputs/period_results.csv")
    parser.add_argument("--resolution-m", type=float, default=25)
    args = parser.parse_args()
    project = args.project.resolve()
    table = args.table.resolve() if args.table else project/"outputs/period_results.csv"
    output = project/"deliverables/kmz"; output.mkdir(parents=True, exist_ok=True)
    scenario_path = project/"scenario.json"; scenario = json.loads(scenario_path.read_text())
    record = {"created_utc": datetime.now(timezone.utc).isoformat(), "status": "in_progress",
              "script": artifact(Path(__file__)), "table": artifact(table), "scenario": artifact(scenario_path),
              "software_versions": {**{name: version(name) for name in ("numpy", "scipy", "matplotlib", "Pillow")},
                                    "GDAL": command(["gdalwarp", "--version"]).strip()},
              "projection_source": "EPSG:26917, NAD83 / UTM zone 17N", "projection_target": "EPSG:4326, WGS84 longitude/latitude",
              "georeferencing": "GDAL/PROJ coordinate transform; RGBA source raster georeferenced in UTM then GDAL-warped to regular WGS84",
              "spatial_display": "Linear interpolation of native receptor values, cropped to refined grid [-1,10] km alongwind and ±1 km crosswind; outside convex hull masked",
              "deposition_interpretation": "µg/m²/h from actual 24-hour native accumulated µg/m² divided by 24 constant valid modeled hours; not deposition velocity",
              "artifacts": []}
    record_path = output/"kmz_provenance.json"
    try:
        if args.resolution_m <= 0:
            raise ValueError("Display resolution must be positive")
        groups = read_table(table)
        if "u2_r1" not in groups:
            raise ValueError("Missing controlled 2m/s rainy baseline")
        record["native_execution"] = verify_native(project, groups)
        xy = groups["u2_r1"]["xy"]
        ll = transform(xy)
        center_x, center_y = float(scenario["center"]["easting_m"]), float(scenario["center"]["northing_m"])
        center_ll = transform(np.array([[center_x, center_y]]))[0]
        if not np.allclose(center_ll, [-82.84, 34.68], rtol=0, atol=1e-6):
            raise ValueError("Independent known source-coordinate georeferencing check failed")
        record["coordinate_check"] = {"known_source_longitude_latitude": [-82.84, 34.68],
                                       "gdal_source_longitude_latitude": center_ll.tolist(), "passed": True}
        bounds = (center_x-1000, center_x+10000, center_y-1000, center_y+1000)
        with tempfile.TemporaryDirectory(prefix="clemson-kmz-") as tmp:
            work = Path(tmp)
            icon = Image.new("RGBA", (24, 24), (255,255,255,0))
            ImageDraw.Draw(icon).ellipse((3,3,21,21), fill=(255,255,255,255))
            icon.save(work/"receptor.png")
            layers, legends, norms = {}, {}, {}
            record["color_scales"], record["layers"] = {}, {}
            for metric in METRICS:
                norm, scale = normalize(groups, metric)
                norms[metric] = norm; record["color_scales"][metric] = scale
                legend = work/f"legend_{metric}.png"; legend_png(legend, metric, norm, scale)
                legends[metric] = legend
            with ThreadPoolExecutor(max_workers=3) as workers:
                tasks = [(name, metric, workers.submit(overlay_png, work, name, metric, group["xy"],
                                                      group["values"][metric], norms[metric], bounds, args.resolution_m))
                         for metric in METRICS for name, group in groups.items()]
                for name, metric, task in tasks:
                    group = groups[name]
                    layer = task.result()
                    layers[f"{name}/{metric}"] = layer
                    record["layers"][f"{name}/{metric}"] = {**layer[1], "native_min": float(group["values"][metric].min()),
                                                             "native_max": float(group["values"][metric].max()),
                                                             "receptor_count": len(xy), "unit": METRICS[metric]["unit"]}
            for metric in METRICS:
                target = output/f"clemson_u2_rain1_{metric}.kmz"
                record["artifacts"].append(write_kmz(target, ["u2_r1"], [metric], groups, scenario, layers, legends, norms, ll, work))
            target = output/"clemson_steady_all_scenarios.kmz"
            record["artifacts"].append(write_kmz(target, sorted(groups), list(METRICS), groups, scenario, layers, legends, norms, ll, work))
        record["status"] = "complete"
        (output/"README.txt").write_text(
            "DIRECT KMZ MAPS — CONTROLLED CLEMSON AERMOD SCENARIOS\n\n"
            "Open a .kmz file directly in Google Earth Pro or another KMZ-capable GIS.\n"
            "The three clemson_u2_rain1 files each show one actual modeled field\n"
            "at 2 m/s with 1 mm/h rain. The combined file contains all ten wind/rain\n"
            "cases and all three quantities; its default view is baseline concentration.\n"
            "Expand a case, select one quantity at a time, and switch other quantities\n"
            "off. The concentration layer is preselected within each case.\n\n"
            "Every quantity includes an interpolated display overlay, units/color\n"
            "legend, and a separately switchable folder of actual native receptor\n"
            "values. Click a receptor to inspect its numerical value. Source and\n"
            "wind-direction markers are included. All modeled images are embedded;\n"
            "no external overlay image server is required. A basemap may separately\n"
            "require connectivity in the GIS application.\n\n"
            "Concentration: micrograms/m3. Dry/wet deposition: micrograms/m2/hour.\n"
            "Flux is derived from validated 24-hour accumulation divided by 24\n"
            "identical valid modeled hours. It is not deposition velocity.\n"
            "Weather is synthetic and constant. The source and emissions are\n"
            "illustrative, not a measured local microplastic inventory.\n\n"
            "Continuous colors linearly interpolate actual native receptor results\n"
            "over the refined display grid [-1,10] km alongwind and +/-1 km across\n"
            "wind; they are not a separate Gaussian-plume calculation. Outside the\n"
            "display extent, absence of an overlay does not imply zero concentration.\n"
            "Each metric has one shared positive logarithmic color scale across all\n"
            "cases. Transparent pixels indicate zero or no display coverage.\n"
            "Point layers retain actual native values, including zeros.\n\n"
            "Georeferencing uses GDAL/PROJ, NAD83 UTM17N to WGS84, and a full\n"
            "raster warp. KMZs passed GDAL LIBKML direct-open, ZIP CRC, XML, local\n"
            "resource/style, image-decoding, coordinate-bound and native-result\n"
            "hash checks. Interactive rendering in Google Earth was not tested.\n"
            "See kmz_provenance.json and the accompanying workbook/methods.\n", encoding="utf-8")
        record["artifacts"].append(artifact(output/"README.txt"))
    except (OSError, ValueError, KeyError, subprocess.CalledProcessError) as exc:
        record["status"] = "failed; KMZ files are not validated for use"
        record["error"] = str(exc)
        record_path.write_text(json.dumps(record, indent=2, allow_nan=False)+"\n")
        raise
    record_path.write_text(json.dumps(record, indent=2, allow_nan=False)+"\n")
    kmz_count = sum(item["path"].endswith(".kmz") for item in record["artifacts"])
    print(f"Saved {kmz_count} verified KMZ files, README and {record_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
