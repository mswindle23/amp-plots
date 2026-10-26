#!/usr/bin/env python3
"""Prepare and run official AERMINUTE on observed NOAA KCEU minute records.

The raw monthly files are downloaded by met_inputs.py, not by this module.
Example using the explicitly documented, unverified sonic-anemometer assumption::

  python3 clemson_amp/scripts/aerminute_inputs.py --project clemson_amp run \
    --aerminute /workspace/.cloud-setup/amp-plots/bin/aerminute \
    --ifw-date 2023-01-01 --assume-ifw

The assumed date is an effective processing date, never a measured commission
date. Without --assume-ifw, supply --ifw-source with the actual installation date.
"""

from __future__ import annotations

import argparse
import calendar
import datetime as dt
import hashlib
import json
import math
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time
import uuid


DEFAULT_BINARY = Path("/workspace/.cloud-setup/amp-plots/bin/aerminute")


def digest(path: Path) -> str:
    result = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            result.update(block)
    return result.hexdigest()


def file_info(path: Path, project: Path) -> dict:
    return dict(path=os.path.relpath(path, project), bytes=path.stat().st_size, sha256=digest(path))


def write_json(path: Path, data: dict) -> None:
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(data, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    temporary.replace(path)


def timestamp() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat()


def prepare(project: Path, year: int, ifw_date: dt.date, assumed: bool,
            ifw_source: str | None, raw_dir: Path | None = None) -> dict:
    if not assumed and not ifw_source:
        raise ValueError("Supply --ifw-source for an actual installation date, or explicitly use --assume-ifw")
    raw_dir = raw_dir or project / "data" / "met" / "asos1min"
    raw_paths = [raw_dir / f"asos-1min-pg1-KCEU-{year}{month:02d}.dat" for month in range(1, 13)]
    for path in raw_paths:
        if not path.is_file() or not path.stat().st_size:
            raise FileNotFoundError(f"Observed monthly NOAA file missing/empty: {path}. Run met_inputs.py prepare first.")
    target = project / "aerminute"
    target.mkdir(parents=True, exist_ok=True)
    relative_paths = [os.path.relpath(path, target) for path in raw_paths]
    if any(len(path) > 240 or '"' in path or "\n" in path for path in relative_paths):
        raise ValueError("AERMINUTE input paths must fit its 250-character Fortran filename fields")
    assumption = (
        "ASSUMED sonic-anemometer (IFW) status. The supplied date is an effective processing date, "
        "NOT a verified IFW installation/commission date. Official NWS commission-date lookup was unavailable. "
        "AERMINUTE July2026 User's Guide section4.1.2 pp8-9 discusses post2009 sonic assumptions for "
        "stations absent from its installation list. Here both installation date and unlisted status remain "
        "unverified; sonic status is an explicit illustrative modeling assumption authorized for this scenario. "
        "Verify with NWS before a definitive study."
    ) if assumed else "Installation date supplied with source reference; consult that reference for evidence."
    lines = [
        "** Observed NOAA KCEU minute winds; no generated or filled observations.",
        "** " + ("ASSUMED IFW sonic status and effective date, NOT verified commission metadata." if assumed
                  else "IFW installation date supplied with source reference in input_provenance.json."),
        f"STARTEND 1 {year} 12 {year}",
        f"IFWGROUP Y {ifw_date.month} {ifw_date.day} {ifw_date.year}",
        "", "DATAFILE STARTING",
        # Fortran list-directed READ treats an unquoted slash as a terminator.
        *[f'"{path}"' for path in relative_paths],
        "DATAFILE FINISHED", "", "OUTFILES STARTING",
        "HOURFILE clemson_1min.dat", "SUMMFILE minute_summary.csv", "OUTFILES FINISHED", "",
    ]
    control = target / "aerminute.inp"
    control.write_text("\n".join(lines), encoding="ascii")
    metadata = {
        "created_utc": timestamp(), "year": year, "station": "KCEU", "wban": "53850",
        "control": file_info(control, project),
        "raw_observed_inputs": [file_info(path, project) for path in raw_paths],
        "ifw": {
            "sonic_status": "ASSUMED" if assumed else "SUPPLIED_WITH_SOURCE",
            "effective_processing_date": ifw_date.isoformat(),
            "verified_commission_date": None if assumed else ifw_date.isoformat(),
            "source_reference": ifw_source,
            "interpretation": assumption,
            "guide": "https://gaftp.epa.gov/Air/aqmg/SCRAM/models/met/aerminute/aerminute_userguide.pdf",
        },
        "scope": "AERMINUTE's official QC and averaging of observed NOAA records; no weather gap fabrication",
    }
    write_json(target / "input_provenance.json", metadata)
    return metadata


def audit_hourfile(path: Path, year: int) -> dict:
    lines = path.read_text(encoding="ascii").splitlines()
    if not lines or not re.search(r"AERMINUTE\s+Version\s+\d{5}", lines[0], re.I):
        raise ValueError("Hourly wind file lacks official AERMINUTE version header")
    if not re.search(r"Call\s+sign:\s*KCEU\b", lines[0], re.I) or not re.search(r"WBAN:\s*53850\b", lines[0], re.I):
        raise ValueError("Hourly wind file station header does not identify KCEU/WBAN53850")
    seen = set()
    counts = dict(valid_noncalm_hours=0, calm_hours=0, missing_or_invalid_hours=0)
    for line_number, line in enumerate(lines[1:], 2):
        if not line.strip():
            continue
        fields = line.split()
        if len(fields) != 6:
            raise ValueError(f"Hourly wind record {line_number} has {len(fields)} fields instead of6")
        yr, month, day, hour = map(int, fields[:4])
        if yr not in (year, year % 100) or not 1 <= hour <= 24:
            raise ValueError(f"Hourly wind record has wrong year/hour at line{line_number}")
        dt.date(year, month, day)
        key = (month, day, hour)
        if key in seen:
            raise ValueError(f"Duplicate hourly wind record: {key}")
        seen.add(key)
        speed, direction = map(float, fields[4:])
        if not all(math.isfinite(value) for value in (speed, direction)):
            raise ValueError(f"Nonfinite hourly wind data at line{line_number}")
        if speed == 999.0 or direction == 999.0:
            counts["missing_or_invalid_hours"] += 1
        elif speed == 0 and direction == 0:
            counts["calm_hours"] += 1
        elif speed > 0 and 0 <= direction <= 360:
            counts["valid_noncalm_hours"] += 1
        else:
            raise ValueError(f"Unexpected wind values at line{line_number}: {speed}, {direction}")
    expected = (366 if calendar.isleap(year) else 365) * 24
    if len(seen) != expected:
        raise ValueError(f"AERMINUTE has {len(seen)} hourly records; expected{expected}")
    if not counts["valid_noncalm_hours"]:
        raise ValueError("No valid noncalm hourly winds were produced")
    return dict(header=lines[0], expected_hour_records=expected, actual_hour_records=len(seen), **counts)


def run(project: Path, binary: Path) -> dict:
    target = project / "aerminute"
    metadata_path = target / "input_provenance.json"
    if not metadata_path.is_file():
        raise FileNotFoundError("Prepare the AERMINUTE control with explicit IFW metadata/assumption before running")
    inputs = json.loads(metadata_path.read_text(encoding="utf-8"))
    if not binary.is_file() or not os.access(binary, os.X_OK):
        raise FileNotFoundError(f"AERMINUTE binary is missing/not executable: {binary}")
    control = target / "aerminute.inp"
    if digest(control) != inputs["control"]["sha256"]:
        raise ValueError("AERMINUTE control differs from its saved provenance; regenerate before running")
    for item in inputs["raw_observed_inputs"]:
        path = project / item["path"]
        if not path.is_file() or digest(path) != item["sha256"]:
            raise ValueError(f"Observed NOAA file differs from saved input provenance: {path}")
    run_id = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "_" + uuid.uuid4().hex[:8]
    outputs = [target / name for name in ("clemson_1min.dat", "minute_summary.csv", "aerminute.log",
               "aerminute.stdout.txt", "bad_records.dat", "good_records.dat", "check_records.dat")]
    archived = []
    for path in outputs:
        if path.exists():
            backup = target / "prior_outputs" / run_id / path.name
            backup.parent.mkdir(parents=True, exist_ok=True)
            archived.append(dict(file_info(path, project), archived_path=os.path.relpath(backup, project)))
            shutil.move(str(path), str(backup))
    result = {
        "run_id": run_id, "started_utc": timestamp(), "status": "failed",
        "command": [str(binary.resolve())], "stdin": control.name + "\n", "cwd": str(target),
        "model_binary": file_info(binary, project), "inputs": inputs,
        "preserved_previous_outputs": archived, "problems": [],
    }
    started = time.monotonic()
    with (target / "aerminute.stdout.txt").open("w", encoding="utf-8") as stream:
        command = subprocess.run([str(binary.resolve())], cwd=target, input=control.name + "\n",
                                 text=True, stdout=stream, stderr=subprocess.STDOUT, check=False)
    result["returncode"] = command.returncode
    result["elapsed_seconds"] = round(time.monotonic() - started, 3)
    text = "\n".join(path.read_text(encoding="utf-8", errors="replace") for path in (
        target / "aerminute.log", target / "aerminute.stdout.txt") if path.is_file())
    if command.returncode:
        result["problems"].append(f"Command exit status{command.returncode}")
    if not re.search(r"\bNormal termination\b", text, re.I) or re.search(r"Abnormal termination|Fortran runtime error|ERROR STOP", text, re.I):
        result["problems"].append("AERMINUTE did not report normal termination")
    for name in ("clemson_1min.dat", "minute_summary.csv", "aerminute.log"):
        path = target / name
        if not path.is_file() or not path.stat().st_size:
            result["problems"].append(f"Current AERMINUTE output missing/empty: {name}")
    if (target / "clemson_1min.dat").is_file():
        try:
            result["hourly_wind_audit"] = audit_hourfile(target / "clemson_1min.dat", int(inputs["year"]))
        except (OSError, ValueError) as exc:
            result["problems"].append(str(exc))
    result["outputs"] = [dict(file_info(path, project), created_by_current_run=True) for path in outputs if path.is_file()]
    if not result["problems"]:
        result["status"] = "passed"
    result["finished_utc"] = timestamp()
    write_json(target / "run_provenance.json", result)
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--project", type=Path, default=Path(__file__).resolve().parents[1])
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("prepare", "run"):
        command = commands.add_parser(name)
        command.add_argument("--year", type=int)
        command.add_argument("--raw-dir", type=Path)
        command.add_argument("--ifw-date", type=dt.date.fromisoformat, metavar="YYYY-MM-DD")
        command.add_argument("--assume-ifw", action="store_true", help="Explicitly assume sonic status/effective date; not a verified installation date")
        command.add_argument("--ifw-source", help="Reference for a supplied actual installation date")
        if name == "run":
            command.add_argument("--aerminute", type=Path, default=DEFAULT_BINARY)
    args = parser.parse_args()
    project = args.project.resolve()
    try:
        scenario = json.loads((project / "scenario.json").read_text(encoding="utf-8"))
        year = args.year or int(scenario["year"])
        if args.ifw_date is not None:
            metadata = prepare(project, year, args.ifw_date, args.assume_ifw, args.ifw_source,
                               args.raw_dir.resolve() if args.raw_dir else None)
            print(f"Prepared observed minute inputs for{year}; IFWstatus={metadata['ifw']['sonic_status']}")
        elif args.command == "prepare" or args.assume_ifw:
            parser.error("Provide --ifw-date; no installation/effective date is inferred")
        if args.command == "run":
            result = run(project, args.aerminute.resolve())
            print(json.dumps({key: result.get(key) for key in ("status", "elapsed_seconds", "hourly_wind_audit", "problems")}, indent=2))
            return 0 if result["status"] == "passed" else 1
        return 0
    except (OSError, ValueError, KeyError) as exc:
        print(f"AERMINUTE setup failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
