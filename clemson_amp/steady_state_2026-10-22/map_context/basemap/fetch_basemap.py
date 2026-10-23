#!/usr/bin/env python3
"""Download and georeference the actual USGS basemap used beneath the plume.

The map is assembled from official 2024 US Topo geospatial PDFs. PyMuPDF
renders the map content; GDAL supplies each PDF's original affine transform
and projection, then clips the map collars and mosaics in model coordinates.
No geographic features are synthesized by this script.

The original downloads are large and are not required in the public package.
Use --source-directory with --offline to reuse the retained verified PDFs.
Use a separate --output directory when verifying a published immutable map.
"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

import fitz
import numpy as np
from PIL import Image


BBOX = (330235.622, 3837297.591, 341735.622, 3840897.591)
WIDTH, HEIGHT, DPI = 3000, 940, 200
API = "https://tnmaccess.nationalmap.gov/api/v1/products?" + urllib.parse.urlencode({
    "bbox": "-82.854,34.663,-82.726,34.697", "datasets": "US Topo Current",
    "max": "10", "outputFormat": "JSON",
})
EXPECTED = {
    "SC_Clemson_20240730_TM_geo.pdf":
        "4781cec6940b4e2ebcb8d64bc2c0f69d29099a139e4a3a03fdf902c75afed98c",
    "SC_Five_Forks_20240412_TM_geo.pdf":
        "b7e0c92aead00a538452653e6058b932962523ce3227b2149b953fe01c970dab",
}
ATTRIBUTION = ("Basemap: USGS The National Map / US Topo "
               "(Clemson and Five Forks, 2024 editions).")


def sha(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def artifact(path: Path) -> dict:
    return {"path": str(path.resolve()), "sha256": sha(path),
            "bytes": path.stat().st_size}


def command(arguments: list[str]) -> str:
    result = subprocess.run(arguments, capture_output=True, text=True, check=True)
    if result.stderr.strip():
        raise RuntimeError(f"Unexpected GIS warning: {result.stderr}")
    return result.stdout


def get(url: str, target: Path) -> None:
    with urllib.request.urlopen(url, timeout=120) as stream, target.open("wb") as out:
        shutil.copyfileobj(stream, out)


def quad_cutline(item: dict, path: Path) -> None:
    b = item["boundingBox"]
    west, south, east, north = (b[k] for k in ("minX", "minY", "maxX", "maxY"))
    value = {"type": "FeatureCollection", "name": "map_quad_extent",
             "crs": {"type": "name", "properties": {"name": "EPSG:4326"}},
             "features": [{"type": "Feature", "properties": {"title": item["title"]},
                           "geometry": {"type": "Polygon", "coordinates": [[
                               [west, south], [east, south], [east, north],
                               [west, north], [west, south]]]}}]}
    path.write_text(json.dumps(value) + "\n")


def render(item: dict, output: Path) -> tuple[Path, dict]:
    filename = Path(item["downloadURL"]).name
    pdf = output / filename
    if sha(pdf) != EXPECTED[filename] or pdf.stat().st_size != item["sizeInBytes"]:
        raise ValueError(f"Official PDF identity differs: {filename}")
    stem = pdf.stem
    png, vrt = output / (stem + "_render.png"), output / (stem + "_render.vrt")
    crop, cutline = output / (stem + "_crop.tif"), output / (stem + "_quad.geojson")
    doc = fitz.open(pdf)
    # This reproduces the configuration used in the delivered rendering.
    # All actual rendered map content remains visible in the final preview;
    # its imagery acquisition date is not inferred from its publication date.
    excluded = {"Map Collar", "Map Elements", "Projection and Grids", "Contours",
                "Shaded Relief", "Images", "Orthoimage"}
    doc.set_layer(-1, off=[key for key, value in doc.get_ocgs().items()
                           if value["name"] in excluded])
    pixels = doc[0].get_pixmap(matrix=fitz.Matrix(DPI / 72, DPI / 72), alpha=False)
    pixels.save(png)
    command(["gdal_translate", "-q", "-oo", f"DPI={DPI}", "-of", "VRT", str(pdf), str(vrt)])
    tree = ET.parse(vrt)
    root = tree.getroot()
    if (int(root.attrib["rasterXSize"]), int(root.attrib["rasterYSize"])) != (pixels.width, pixels.height):
        raise ValueError("Independent PDF renderer and geospatial source have different dimensions")
    for source in root.findall(".//SourceFilename"):
        source.text = str(png.resolve())
        source.attrib["relativeToVRT"] = "0"
    tree.write(vrt, encoding="utf-8", xml_declaration=True)
    quad_cutline(item, cutline)
    command(["gdalwarp", "-q", "-overwrite", "-t_srs", "EPSG:26917",
             "-te", *map(str, BBOX), "-ts", str(WIDTH), str(HEIGHT),
             "-cutline", str(cutline), "-dstalpha", "-r", "bilinear",
             "-co", "COMPRESS=DEFLATE", str(vrt), str(crop)])
    info = json.loads(command(["gdalinfo", "-oo", f"DPI={DPI}", "-json", str(pdf)]))
    info_path = output / (stem + "_gdalinfo.json")
    info_path.write_text(json.dumps(info, indent=2) + "\n")
    source = {"title": item["title"], "publication_date": item["publicationDate"],
              "url": item["downloadURL"], "metadata_url": item["metaUrl"],
              **artifact(pdf), "bounding_box_wgs84": item["boundingBox"],
              "pdf_gdal_metadata": artifact(info_path),
              "source_geotransform_at_200dpi": info["geoTransform"],
              "source_raster_size_at_200dpi": info["size"]}
    return crop, source


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path(__file__).resolve().parent)
    parser.add_argument("--source-directory", type=Path)
    parser.add_argument("--offline", action="store_true")
    args = parser.parse_args()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    cache = args.source_directory.resolve() if args.source_directory else output
    products = output / "usgs_products.json"
    if cache != output and (cache / products.name).is_file():
        shutil.copy2(cache / products.name, products)
    if not products.is_file():
        if args.offline:
            raise FileNotFoundError("No cached USGS product metadata")
        get(API, products)
    items = [item for item in json.loads(products.read_text())["items"]
             if Path(item["downloadURL"]).name in EXPECTED]
    if len(items) != 2:
        raise ValueError("Expected both original 2024 official map products")
    for item in items:
        name = Path(item["downloadURL"]).name
        target = output / name
        if cache != output and (cache / name).is_file():
            shutil.copy2(cache / name, target)
        if not target.is_file():
            if args.offline:
                raise FileNotFoundError(name)
            get(item["downloadURL"], target)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda item: render(item, output), items))
    geotiff, png = output / "usgs_topo.tif", output / "usgs_topo.png"
    command(["gdalwarp", "-q", "-overwrite", "-t_srs", "EPSG:26917",
             "-te", *map(str, BBOX), "-ts", str(WIDTH), str(HEIGHT),
             "-srcalpha", "-dstalpha", "-r", "bilinear", "-co", "COMPRESS=DEFLATE",
             *[str(crop) for crop, _ in results], str(geotiff)])
    command(["gdal_translate", "-q", "-of", "PNG", str(geotiff), str(png)])
    info = json.loads(command(["gdalinfo", "-json", str(geotiff)]))
    gt = info["geoTransform"]
    pixels = np.asarray(Image.open(png))
    extent = dict(zip(("xmin", "ymin", "xmax", "ymax"), BBOX))
    extent["spatialReference"] = {"wkid": 26917}
    metadata = {"status": "complete", "retrieved_utc": datetime.now(timezone.utc).isoformat(),
                "image": {**artifact(png), "width_px": WIDTH, "height_px": HEIGHT},
                "geotiff": artifact(geotiff), "extent": extent, "extent_array": list(BBOX),
                "crs_epsg": 26917, "crs": "EPSG:26917", "geotransform": gt,
                "source_url": API, "request_url": API, "raw_export_json_path": str(products),
                "attribution": ATTRIBUTION, "source_products": [s for _, s in results],
                "processing": {"pdf_renderer": f"PyMuPDF {fitz.VersionBind}", "pdf_render_dpi": DPI,
                               "source_georeference": "Original GDAL geospatial-PDF CRS and affine transform copied to same-size independently rendered image via VRT.",
                               "quad_collar_mask": "Official WGS84 map product bounding boxes.",
                               "mosaic": "GDAL bilinear warp to exact model EPSG:26917 extent.",
                               "date_caveat": "2024 is the edition/publication year, not the acquisition date of underlying imagery or observations of synthetic plume conditions."},
                "validation": {"png_decoded": True, "rgba_shape": list(pixels.shape),
                               "north_up": gt[2] == 0 and gt[4] == 0,
                               "transparent_pixels": int(np.count_nonzero(pixels[:, :, 3] == 0)),
                               "source_expected_bytes_match": True,
                               "gdal_version": command(["gdalinfo", "--version"]).strip()}}
    (output / "basemap_metadata.json").write_text(json.dumps(metadata, indent=2) + "\n")
    (output / "usgs_topo.pgw").write_text("\n".join(f"{v:.15f}" for v in
        (gt[1], gt[4], gt[2], gt[5], gt[0] + gt[1] / 2, gt[3] + gt[5] / 2)) + "\n")
    print(json.dumps({"status": "complete", "image": metadata["image"],
                      "extent": extent}, indent=2))


if __name__ == "__main__":
    main()
