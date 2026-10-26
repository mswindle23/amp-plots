#!/usr/bin/env python3
"""Check Excel integrity, full declared dimensions and selected native anchors.

The worksheet XML is streamed without allocating millions of Python cell
objects. Anchor values are selected directly from authentic native files.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import xml.etree.ElementTree as ET
import zipfile

import numpy as np


NS = {"s": "http://schemas.openxmlformats.org/spreadsheetml/2006/main",
      "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships"}


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def selected_rows(archive: zipfile.ZipFile, member: str, numbers: set[int]) -> dict:
    wanted = {number: f'<row r="{number}"'.encode() for number in numbers}
    rows, buffer = {}, b""
    with archive.open(member) as stream:
        while wanted:
            block = stream.read(1 << 20)
            if not block:
                break
            buffer += block
            incomplete = None
            for number, marker in list(wanted.items()):
                start = buffer.find(marker)
                if start < 0:
                    continue
                stop = buffer.find(b"</row>", start)
                if stop < 0:
                    incomplete = start if incomplete is None else min(incomplete, start)
                    continue
                node = ET.fromstring(buffer[start:stop + 6])
                cells = {}
                for cell in node.findall("c"):
                    column = re.match(r"[A-Z]+", cell.attrib["r"]).group()
                    if cell.attrib.get("t") == "inlineStr":
                        value = "".join(cell.itertext())
                    else:
                        value = cell.findtext("v")
                        value = float(value) if value is not None else ""
                    cells[column] = value
                rows[number] = cells
                del wanted[number]
            buffer = buffer[incomplete:] if incomplete is not None else buffer[-64:]
    if wanted:
        raise ValueError(f"Missing Excel anchor rows in {member}: {sorted(wanted)}")
    return rows


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args()
    project = args.project.resolve()
    path = project / "outputs" / "clemson_steady_state_inputs_outputs.xlsx"
    scenario = json.loads((project / "scenario.json").read_text())
    cases = sorted(scenario["particle_cases"], key=lambda case: (case["wind_speed_m_s"], case["precipitation_mm_h"]))
    receptor = np.loadtxt(project / "aermod" / cases[0]["name"] / "concentration" / "annual.plt", comments="*", usecols=(0, 1, 2))
    order = np.lexsort((receptor[:, 1], receptor[:, 0]))
    xy = receptor[order, :2]
    count = len(xy)
    target = np.array([scenario["center"]["easting_m"] + 1000, scenario["center"]["northing_m"]])
    index = int(np.linalg.norm(xy - target, axis=1).argmin())
    if np.linalg.norm(xy[index] - target) > 0.1:
        raise ValueError("No native receptor at the intended 1km projected-east anchor")
    expectations = {"HourlyResults": {}, "PeriodResults": {}}
    for case_index, case in enumerate(cases):
        period_values, hourly_values = {}, {}
        for metric in ("concentration", "dry_deposition", "wet_deposition"):
            directory = project / "aermod" / case["name"] / metric
            period = np.loadtxt(directory / "annual.plt", comments="*", usecols=(0, 1, 2))
            period = period[np.lexsort((period[:, 1], period[:, 0]))]
            period_values[metric] = float(period[index, 2])
            # The main independent audit already proves every hourly field
            # identical. Read the 1st-hour anchor directly from the ASCII file.
            for line in (directory / "hourly.plt").read_text().splitlines():
                if not line.strip() or line.startswith("*"):
                    continue
                fields = line.split()
                if float(fields[0]) == xy[index, 0] and float(fields[1]) == xy[index, 1]:
                    hourly_values[metric] = float(fields[2])
                    first_tag = int(fields[8])
                    break
            else:
                raise ValueError(f"Missing native hourly anchor: {directory}")
        common = {"case": case["name"], "wind_speed_m_s": case["wind_speed_m_s"],
                  "rain_mm_h": case["precipitation_mm_h"], "x_m": float(xy[index, 0]), "y_m": float(xy[index, 1])}
        for hour in (1, 24):
            row = 2 + case_index * 24 * count + (hour - 1) * count + index
            expectations["HourlyResults"][row] = {
                **common, "hour_ending_lst": hour, "date_hour_native": first_tag - 1 + hour,
                "concentration_ug_m3": hourly_values["concentration"],
                "dry_hour_amount_ug_m2": hourly_values["dry_deposition"],
                "wet_hour_amount_ug_m2": hourly_values["wet_deposition"],
                "dry_flux_ug_m2_h": hourly_values["dry_deposition"],
                "wet_flux_ug_m2_h": hourly_values["wet_deposition"], "native_averaging": "1-HR"}
        expectations["PeriodResults"][2 + case_index * count + index] = {
            **common, "requested_hours": 24, "concentration_ug_m3": period_values["concentration"],
            "dry_accumulated_ug_m2": period_values["dry_deposition"],
            "wet_accumulated_ug_m2": period_values["wet_deposition"],
            "dry_flux_ug_m2_h": period_values["dry_deposition"] / 24,
            "wet_flux_ug_m2_h": period_values["wet_deposition"] / 24,
            "native_averaging": "PERIOD"}
    dimensions, anchor_count = {}, 0
    with zipfile.ZipFile(path) as archive:
        if archive.testzip() is not None:
            raise ValueError("Excel archive failed CRC verification")
        relationships = ET.fromstring(archive.read("xl/_rels/workbook.xml.rels"))
        targets = {node.attrib["Id"]: "xl/" + node.attrib["Target"].lstrip("/") for node in relationships}
        workbook = ET.fromstring(archive.read("xl/workbook.xml"))
        sheets = {node.attrib["name"]: targets[node.attrib[f"{{{NS['r']}}}id"]]
                  for node in workbook.find("s:sheets", NS)}
        for name, member in sheets.items():
            with archive.open(member) as stream:
                prefix = stream.read(4096)
            match = re.search(rb'<dimension ref="([^"]+)"', prefix)
            if not match:
                raise ValueError(f"No explicit Excel sheet dimensions: {name}")
            dimension = match.group(1).decode()
            dimensions[name] = {"range": dimension, "data_rows": int(re.search(r"(\d+)$", dimension).group()) - 1}
            if name not in expectations:
                continue
            rows = selected_rows(archive, member, set(expectations[name]) | {1})
            headers = {value: column for column, value in rows[1].items()}
            for number, expected in expectations[name].items():
                for field, value in expected.items():
                    actual = rows[number][headers[field]]
                    if isinstance(value, str):
                        if actual != value:
                            raise ValueError(f"Excel/native string mismatch {name}:{number}/{field}")
                    elif not np.isclose(actual, value, rtol=2e-14, atol=1e-300):
                        raise ValueError(f"Excel/native numeric mismatch {name}:{number}/{field}: {actual} != {value}")
                anchor_count += 1
        for name, expected in (("HourlyResults", 24 * count * len(cases)),
                               ("PeriodResults", count * len(cases)),
                               ("Maximum1h", count * len(cases)),
                               ("WeatherSurface", 24 * len(cases)),
                               ("WeatherProfiles", 24 * len(cases)),
                               ("TerrainReceptors", count)):
            if dimensions[name]["data_rows"] != expected:
                raise ValueError(f"Incorrect full Excel dimension for {name}: {dimensions[name]}")
    result = {"status": "passed", "xlsx_crc": "passed", "sheet_dimensions": dimensions,
              "selected_native_anchor_rows": anchor_count,
              "anchor_description": "1km projected-east receptor for all10cases, hour1/hour24andPERIOD; direct native ASCII reference",
              "workbook": {"path": str(path), "sha256": digest(path), "bytes": path.stat().st_size},
              "script": {"path": str(Path(__file__).resolve()), "sha256": digest(Path(__file__))}}
    (project / "independent_workbook_validation.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({"status": "passed", "selected_native_anchor_rows": anchor_count,
                      "workbook_bytes": path.stat().st_size, "sheets": len(dimensions)}))


if __name__ == "__main__":
    main()
