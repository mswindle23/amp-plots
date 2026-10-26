#!/usr/bin/env python3
"""Add an embedded, correctly warped USGS map beneath verified AERMOD KMZs."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess
import tempfile
import xml.etree.ElementTree as ET
import zipfile

from PIL import Image

from build_kmz import read_table, verify_native, validate_kmz

NS = "http://www.opengis.net/kml/2.2"
ET.register_namespace("", NS)


def sha256(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def artifact(path: Path) -> dict:
    return {"path": str(path.resolve()), "sha256": sha256(path), "bytes": path.stat().st_size}


def command(args: list[str]) -> str:
    result = subprocess.run(args, capture_output=True, text=True, check=True)
    return result.stdout


def node(parent, tag: str, value=None):
    child = ET.SubElement(parent, f"{{{NS}}}{tag}")
    if value is not None:
        child.text = str(value)
    return child


def metadata_image(project: Path, metadata: dict) -> Path:
    item = metadata.get("image", metadata.get("raster", {}))
    value = item.get("path") if isinstance(item, dict) else item
    value = value or metadata.get("image_path")
    if not value:
        raise ValueError("Basemap metadata does not name its image")
    path = Path(value)
    path = path if path.is_absolute() else project / path
    if not path.is_file():
        raise FileNotFoundError(path)
    if isinstance(item, dict) and item.get("sha256") and sha256(path) != item["sha256"]:
        raise ValueError("Basemap image changed after its retrieval audit")
    return path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args()
    project = args.project.resolve()
    metadata_file = project / "map_context/basemap/basemap_metadata.json"
    metadata = json.loads(metadata_file.read_text())
    image = metadata_image(project, metadata)
    extent = metadata["extent"]
    xmin, ymin, xmax, ymax = [float(extent[key]) for key in ("xmin", "ymin", "xmax", "ymax")]
    if not xmin < xmax or not ymin < ymax:
        raise ValueError("Invalid basemap extent")
    wkid = extent.get("spatialReference", {}).get("wkid", 26917)
    if int(wkid) != 26917:
        raise ValueError("This context export requires the audited native UTM17N basemap")
    native_checks = verify_native(project, read_table(project / "outputs/period_results.csv"))
    original = project / "deliverables/kmz/clemson_steady_all_scenarios.kmz"
    original_provenance = project / "deliverables/kmz/kmz_provenance.json"
    old = json.loads(original_provenance.read_text())
    matches = [entry for entry in old["artifacts"] if Path(entry["path"]).name == original.name]
    if len(matches) != 1 or sha256(original) != matches[0]["sha256"]:
        raise ValueError("Original verified model KMZ changed")
    destination = project / "map_context/earth"
    destination.mkdir(parents=True, exist_ok=True)
    target = destination / "clemson_plume_on_usgs_map.kmz"
    with tempfile.TemporaryDirectory(prefix="clemson-map-kmz-") as temporary:
        work = Path(temporary)
        native, warped, geographic_png = work / "native.tif", work / "geographic.tif", work / "usgs_basemap.png"
        command(["gdal_translate", "-q", "-of", "GTiff", "-a_srs", "EPSG:26917", "-a_ullr",
                 str(xmin), str(ymax), str(xmax), str(ymin), str(image), str(native)])
        command(["gdalwarp", "-q", "-overwrite", "-s_srs", "EPSG:26917", "-t_srs", "EPSG:4326",
                 "-r", "bilinear", "-dstalpha", "-of", "GTiff", str(native), str(warped)])
        info = json.loads(command(["gdalinfo", "-json", str(warped)]))
        command(["gdal_translate", "-q", "-of", "PNG", str(warped), str(geographic_png)])
        west, south = info["cornerCoordinates"]["lowerLeft"]
        east, north = info["cornerCoordinates"]["upperRight"]
        if not (-84 < west < east < -81 and 33 < south < north < 36):
            raise ValueError("Geographic basemap bounds are outside Clemson")
        with Image.open(geographic_png) as check:
            check.verify()
        with zipfile.ZipFile(original) as source:
            if source.testzip():
                raise ValueError("Original model KMZ CRC failed")
            root = ET.fromstring(source.read("doc.kml"))
            doc = root.find(f"{{{NS}}}Document")
            if doc is None:
                raise ValueError("Original KMZ has no KML Document")
            doc.find(f"{{{NS}}}name").text = "Clemson AERMOD plume on official USGS map"
            description = doc.find(f"{{{NS}}}description")
            description.text = ((description.text or "") + " Embedded basemap: " + metadata["attribution"]
                                + ". Official 2024 USGS quadrangles; roads and names are geographic context, "
                                  "not observed microplastic measurements. Background and all modeled images "
                                  "are embedded for offline use. Baseline concentration is visible initially.")
            # Original model PNGs have alpha195/255. An additional 166/255
            # display multiplier gives about50% opacity, retaining real road
            # context without modifying any native quantity or raster color.
            model_overlays = list(doc.findall(f".//{{{NS}}}GroundOverlay"))
            if len(model_overlays) != 30:
                raise ValueError("Expected all30 original model overlays")
            for model_overlay in model_overlays:
                color = model_overlay.find(f"{{{NS}}}color")
                if color is None:
                    raise ValueError("Original modeled overlay lacks its color control")
                color.text = "a6ffffff"
            overlay = ET.Element(f"{{{NS}}}GroundOverlay")
            node(overlay, "name", "USGS topographic map — roads, water and place names")
            node(overlay, "visibility", 1)
            node(overlay, "description", metadata["attribution"])
            node(overlay, "color", "ffffffff")
            node(overlay, "drawOrder", -10)
            node(node(overlay, "Icon"), "href", "context/usgs_basemap.png")
            box = node(overlay, "LatLonBox")
            for key, value in (("north", north), ("south", south), ("east", east), ("west", west)):
                node(box, key, value)
            # Append after metadata/styles and before the first feature folder;
            # drawOrder keeps this background below all existing model overlays.
            first_folder = next((i for i, child in enumerate(doc) if child.tag == f"{{{NS}}}Folder"), len(doc))
            doc.insert(first_folder, overlay)
            with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as output:
                for item in source.infolist():
                    if item.filename != "doc.kml":
                        output.writestr(item.filename, source.read(item.filename))
                output.writestr("doc.kml", ET.tostring(root, encoding="utf-8", xml_declaration=True))
                output.write(geographic_png, "context/usgs_basemap.png")
        validation = validate_kmz(target)
        report = {
            "status": "complete", "created_utc": datetime.now(timezone.utc).isoformat(),
            "script": artifact(Path(__file__)), "basemap_metadata": artifact(metadata_file),
            "basemap_image": artifact(image), "original_model_kmz": artifact(original),
            "original_kmz_provenance": artifact(original_provenance),
            "native_fields_verified": len(native_checks),
            "native_result_verification": native_checks,
            "geographic_basemap_bounds": {"west": west, "south": south, "east": east, "north": north},
            "coordinate_system": "Native NAD83 UTM17N image fully warped through GDAL to WGS84; no corner-only shortcut",
            "attribution": metadata["attribution"],
            "model_values_modified": False,
            "model_layer_display_color": "a6ffffff",
            "model_layer_effective_opacity": (195 / 255) * (166 / 255),
            "validation": validation, "artifacts": [artifact(target)],
        }
        (destination / "map_context_kmz_provenance.json").write_text(json.dumps(report, indent=2, allow_nan=False) + "\n")
    print(json.dumps({"kmz": str(target), "bytes": target.stat().st_size,
                      "native_fields_verified": len(native_checks), "validation": "passed"}))


if __name__ == "__main__":
    main()
