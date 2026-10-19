#!/usr/bin/env python3
"""Retrieve observed NOAA meteorology, audit it, and prepare/run modern AERMET.

Raw observations are never synthesized. Unknown precipitation remains a separate class.
Existing files are reused only after checksum verification; differing user files are preserved.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import csv
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
import gzip
import hashlib
import io
import json
import math
from pathlib import Path
import re
import subprocess
import sys
import tempfile
from urllib.error import HTTPError, URLError
from urllib.request import urlopen
import zipfile

PROJECT = Path(__file__).resolve().parents[1]
NOAA = "https://www.ncei.noaa.gov"
UPPER_CANDIDATES = {"KFFC": "USM00072215", "KGSO": "USM00072317", "KCHS": "USM00072208"}
TIME_ADJUST = 5


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def write_preserving(path: Path, data: str | bytes) -> None:
    """Write new or byte-identical content, refusing to overwrite different files."""
    payload = data.encode("utf-8") if isinstance(data, str) else data
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if path.read_bytes() != payload:
            raise RuntimeError(f"Preserving existing differing file: {path}")
        return
    with path.open("xb") as stream:
        stream.write(payload)


def write_json(path: Path, value: object) -> None:
    write_preserving(path, json.dumps(value, indent=2, sort_keys=True) + "\n")


def download(url: str, destination: Path, offline: bool = False) -> Path:
    """HTTPS download with a retained provenance/checksum sidecar and safe caching."""
    sidecar = destination.with_suffix(destination.suffix + ".provenance.json")
    if destination.exists():
        if not sidecar.exists():
            raise RuntimeError(f"Existing file has no provenance; preserve and inspect: {destination}")
        provenance = json.loads(sidecar.read_text())
        if provenance["url"] != url or provenance["sha256"] != sha256(destination):
            raise RuntimeError(f"Cached file failed URL/checksum verification: {destination}")
        return destination
    if offline:
        raise RuntimeError(f"Missing cached observation/metadata: {destination}; required URL {url}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    # urllib's default TLS certificate verification remains enabled.
    with tempfile.NamedTemporaryFile(dir=destination.parent, delete=False) as output:
        temporary = Path(output.name)
        try:
            with urlopen(url, timeout=120) as response:
                while block := response.read(1024 * 1024):
                    output.write(block)
        except BaseException:
            temporary.unlink(missing_ok=True)
            raise
    if destination.exists():
        temporary.unlink()
        raise RuntimeError(f"File appeared during download; preserved: {destination}")
    temporary.rename(destination)
    write_json(sidecar, {
        "url": url, "retrieved_utc": datetime.now(timezone.utc).isoformat(),
        "bytes": destination.stat().st_size, "sha256": sha256(destination),
        "integrity_note": "SHA256 records retrieved content; official NOAA HTTPS supplies origin authentication.",
    })
    print(f"Downloaded {destination.name} ({destination.stat().st_size:,} bytes)")
    return destination


def surface_station(metadata: Path, icao: str, year: int) -> dict:
    with metadata.open(newline="") as stream:
        candidates = [row for row in csv.DictReader(stream)
                      if row["ICAO"] == icao and row["WBAN"] != "99999"
                      and row["USAF"] != "999999"
                      and row["BEGIN"] <= f"{year}0101"
                      and row["END"] >= f"{year + 1}0101"]
    if len(candidates) != 1:
        raise RuntimeError(f"Need one verified {icao} station history covering {year}: found {len(candidates)}")
    row = candidates[0]
    result = {
        "icao": icao, "usaf": row["USAF"], "wban": row["WBAN"], "name": row["STATION NAME"],
        "latitude": float(row["LAT"]), "longitude": float(row["LON"]),
        "elevation_m": float(row["ELEV(M)"]), "history_begin": row["BEGIN"], "history_end": row["END"],
        "anemometer_height_m": 7.92,
        "anemometer_source": "EPA AERMET26135 mod_surface.f90 ASOS table (KCEU/KGSP); not a period-specific relocation history",
    }
    if result["elevation_m"] == -999.9:
        raise RuntimeError(f"Missing station elevation for {icao}")
    return result


def distance_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    lat1, lat2, dlat, dlon = map(math.radians, (lat1, lat2, lat2 - lat1, lon2 - lon1))
    a = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    return 6371.0088 * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def upper_stations(metadata: Path, year: int, center: dict) -> list[dict]:
    candidates = []
    for line in metadata.read_text().splitlines():
        if line[:11] not in UPPER_CANDIDATES.values():
            continue
        station = {
            "igra_id": line[:11], "latitude": float(line[12:20]), "longitude": float(line[21:30]),
            "elevation_m": float(line[31:37]), "name": line[41:71].strip(),
            "first_year": int(line[72:76]), "last_year": int(line[77:81]),
            "inventory_soundings_all_years": int(line[82:88]),
        }
        if station["first_year"] <= year <= station["last_year"] and station["elevation_m"] != -999.9:
            station["icao_candidate"] = next(k for k, v in UPPER_CANDIDATES.items() if v == station["igra_id"])
            station["aermet_id"] = re.sub(r"^[A-Z]+", "", station["igra_id"])
            station["distance_to_scenario_km"] = round(distance_km(
                center["latitude"], center["longitude"], station["latitude"], station["longitude"]), 3)
            candidates.append(station)
    if not candidates:
        raise RuntimeError("No requested IGRA candidates cover the selected year")
    return sorted(candidates, key=lambda station: station["distance_to_scenario_km"])


def make_surface_input(archives: list[Path], target: Path, year: int) -> tuple[dict, list[dict]]:
    """Preserve fixed-width ISD, retaining target UTC year plus following-year padding."""
    records = []
    by_hour: dict[datetime, list[str]] = defaultdict(list)
    elevations = Counter()
    for archive in archives:
        with gzip.open(archive, "rt", encoding="ascii") as stream:
            for line in stream:
                stamp = datetime.strptime(line[15:27], "%Y%m%d%H%M")
                if not datetime(year, 1, 1) <= stamp < datetime(year + 1, 1, 3):
                    continue
                records.append(line)
                elevations[line[46:51]] += 1
                if stamp.minute not in (0,) and stamp.minute < 30:
                    continue
                # AERMET accepts observations in the 30 minutes up to the hour.
                ending = stamp.replace(minute=0) + timedelta(hours=bool(stamp.minute)) - timedelta(hours=TIME_ADJUST)
                if (ending - timedelta(microseconds=1)).year == year:
                    by_hour[ending].append(line)
    if not records:
        raise RuntimeError("No target-year ISD observations; no input was fabricated")
    write_preserving(target, "".join(records))
    rows = []
    counts = Counter()
    start, end = datetime(year, 1, 1, 1), datetime(year + 1, 1, 1)
    for hour_index in range(int((end - start).total_seconds() / 3600) + 1):
        ending = start + timedelta(hours=hour_index)
        lines = by_hour.get(ending, [])
        # Audit raw candidate observations independently of AERMET's duplicate-merging rules.
        fields = [match for line in lines for match in re.finditer(r"AA1(\d{2})(\d{4})(.)(.)", line)
                  if match.group(1) == "01"]
        valid = [field for field in fields if field.group(2) != "9999" and field.group(4) not in "2367"]
        amounts = [int(field.group(2)) / 10 for field in valid]
        trace = any(field.group(3) == "2" for field in valid)
        if not lines:
            status = "no_surface_observation"
        elif not fields:
            status = "no_one_hour_precipitation_report"
        elif not valid:
            status = "missing_or_rejected_precipitation"
        elif any(amount > 0 for amount in amounts):
            status = "observed_wet"
        elif trace:
            status = "observed_trace"
        else:
            status = "observed_zero"
        counts[status] += 1
        if any(line[65:69] != "9999" for line in lines):
            counts["hours_with_nonmissing_wind_speed_candidate"] += 1
        date = ending - timedelta(microseconds=1)
        rows.append({
            "date_lst": date.strftime("%Y-%m-%d"), "hour_ending_lst": date.hour + 1,
            "status": status, "eligible_raw_records": len(lines), "one_hour_precip_fields": len(fields),
            "max_reported_precip_mm": max(amounts) if amounts else "",
            "condition_codes": "".join(sorted({field.group(3) for field in fields})),
            "quality_codes": "".join(sorted({field.group(4) for field in fields})),
        })
    audit = {
        "year": year, "expected_hours": len(rows), "status_counts": dict(counts),
        "raw_record_elevations_m": {str(int(k)): v for k, v in sorted(elevations.items())},
        "method": "Per LST hour: inspect any raw candidate record on the hour or in prior30min; AA1 accumulation period01 only. This is an independent coverage audit, not a recreation of AERMET duplicate merging.",
        "quality_policy": "Missing amount9999 and quality2/3/6/7 excluded; all raw condition and quality codes retained for review.",
        "important": "AERMET defaults absent AA101 to zero. Unknown/no-report hours must not be interpreted as observed dry hours. max_reported_precip_mm is a candidate-hour diagnostic, not a replacement forcing dataset.",
    }
    return audit, rows


def make_upper_input(archive: Path, target: Path, station: dict, year: int) -> dict:
    start, end = datetime(year, 1, 1) - timedelta(days=2), datetime(year + 1, 1, 1) + timedelta(days=2)
    selected = bytearray()
    dates = Counter()
    nominal12 = set()
    keep = False
    with zipfile.ZipFile(archive) as bundle:
        members = [name for name in bundle.namelist() if Path(name).name == station["igra_id"] + "-data.txt"]
        if len(members) != 1:
            raise RuntimeError(f"Unexpected IGRA archive members: {archive}")
        with bundle.open(members[0]) as stream:
            for line in stream:
                if line.startswith(b"#"):
                    fields = line.decode("ascii").split()
                    if fields[0] != "#" + station["igra_id"]:
                        raise RuntimeError("IGRA station header disagrees with selected inventory station")
                    date = datetime(*map(int, fields[1:4]))
                    keep = start <= date < end
                    if keep:
                        dates[date.strftime("%Y-%m-%d")] += 1
                        if int(fields[4]) == 12 and date.year == year:
                            nominal12.add(date.strftime("%Y-%m-%d"))
                if keep:
                    selected.extend(line)
    if not selected:
        raise RuntimeError("No IGRA soundings in target year; no substitute observations were invented")
    write_preserving(target, bytes(selected))
    days = (datetime(year + 1, 1, 1) - datetime(year, 1, 1)).days
    all_dates = {(datetime(year, 1, 1) + timedelta(days=i)).strftime("%Y-%m-%d") for i in range(days)}
    return {"target_year": year, "retained_soundings_with_padding": sum(dates.values()),
            "first_retained_utc_date": min(dates), "last_retained_utc_date": max(dates),
            "target_year_dates_without_any_sounding": sorted(all_dates - dates.keys()),
            "target_year_dates_without_nominal_12UTC_sounding": sorted(all_dates - nominal12),
            "note": "Morning-sounding suitability is finally checked by AERMET selection/QA; nominal12UTC count alone is not validation."}


def coordinate(value: float, positive: str, negative: str) -> str:
    return f"{abs(value):.4f}{positive if value >= 0 else negative}"


def preserve_hourly_baseline(project: Path) -> None:
    directory = project / "aermet"
    backup = directory / "hourly_baseline"
    # This archive is immutable: never replace an earlier baseline with revised outputs.
    for name in ("aermet1.inp", "aermet2.inp", "aermet1.msg", "aermet1.rpt", "aermet2.msg", "aermet2.rpt",
                 "aermet1.stdout.txt", "aermet1.stderr.txt", "aermet2.stdout.txt", "aermet2.stderr.txt",
                 "clemson.sfc", "clemson.pfl", "run_provenance.json"):
        source = directory / name
        if source.exists():
            write_preserving(backup / name, source.read_bytes())


def prepare(project: Path = PROJECT, year: int = 2023, offline: bool = False, surface_icao: str = "KCEU",
            minute_winds: bool | None = None) -> dict:
    scenario = json.loads((project / "scenario.json").read_text())
    if year != scenario["year"]:
        raise RuntimeError("Requested year disagrees with scenario.json; update the scenario deliberately")
    data = project / "data" / "met"
    isd_inventory = download(NOAA + "/pub/data/noaa/isd-history.csv", data / "isd-history.csv", offline)
    igra_inventory = download(NOAA + "/pub/data/igra/igra2-station-list.txt", data / "igra2-station-list.txt", offline)
    surface = surface_station(isd_inventory, surface_icao, year)
    existing_deck = project / "aermet" / "aermet2.inp"
    if minute_winds is None:
        minute_winds = existing_deck.exists() and "ASOS1MIN" in existing_deck.read_text()
    if minute_winds:
        def minute_download(month: int) -> Path:
            name = f"asos-1min-pg1-{surface_icao}-{year}{month:02}.dat"
            return download(f"{NOAA}/data/automated-surface-observing-system-one-minute-pg1/access/{year}/{month:02}/{name}",
                            data / "asos1min" / name, offline)
        with ThreadPoolExecutor(max_workers=3) as pool:
            list(pool.map(minute_download, range(1, 13)))
    uppers = upper_stations(igra_inventory, year, scenario["center"])
    upper = uppers[0]
    archives = [download(f"{NOAA}/pub/data/noaa/{y}/{surface['usaf']}-{surface['wban']}-{y}.gz",
                         data / f"{surface['usaf']}-{surface['wban']}-{y}.gz", offline)
                for y in (year, year + 1)]
    surface_path = data / f"{surface_icao}_{year}_padded.isd"
    precip, rows = make_surface_input(archives, surface_path, year)
    archive_name = upper["igra_id"] + "-data.txt.zip"
    upper_archive = download(f"{NOAA}/data/integrated-global-radiosonde-archive/access/data-por/{archive_name}",
                             data / archive_name, offline)
    upper_path = data / f"{upper['igra_id']}_{year}_padded.txt"
    upper_audit = make_upper_input(upper_archive, upper_path, upper, year)
    write_json(data / "precipitation_audit.json", precip)
    text = io.StringIO(newline="")
    writer = csv.DictWriter(text, fieldnames=list(rows[0]))
    writer.writeheader()
    writer.writerows(rows)
    write_preserving(data / "hourly_precipitation_coverage.csv", text.getvalue())
    write_json(data / "upperair_audit.json", upper_audit)
    selection = {
        "year": year, "surface": surface, "upperair": upper, "upperair_candidates": uppers,
        "surface_selection_reason": "KCEU is the local candidate with observed precipitation coverage audited separately; no silent station fallback.",
        "upperair_selection_reason": "Nearest of KFFC/KGSO/KCHS with inventory coverage. Actual gaps are retained and documented in upperair_audit.json; no soundings are synthesized and no automatic regional-station substitution is performed.",
        "utc_to_local_standard_time_hours": TIME_ADJUST,
        "surface_characteristics": {"albedo": 0.20, "Bowen_ratio": 1.0, "roughness_length_m": 0.10,
                                    "frequency": "ANNUAL", "sectors": 1,
                                    "status": "Illustrative assumptions; not an AERSURFACE characterization or measured site data"},
        "inputs": {surface_path.name: sha256(surface_path), upper_path.name: sha256(upper_path)},
        "source_note": "NOAA station-history elevation is supplied explicitly; AERMET uses any nonmissing elevation in the raw ISD file in preference to that value.",
        "raw_precipitation_audit": "precipitation_audit.json", "upperair_audit": "upperair_audit.json",
    }
    write_json(data / "met_selection.json", selection)
    sf_lat, sf_lon = coordinate(surface["latitude"], "N", "S"), coordinate(surface["longitude"], "E", "W")
    ua_lat, ua_lon = coordinate(upper["latitude"], "N", "S"), coordinate(upper["longitude"], "E", "W")
    deck1 = f"""** Observed NOAA meteorology; AERMET24142+ / 26135 syntax. No synthesized weather.
JOB
  MESSAGES aermet1.msg
  REPORT aermet1.rpt
SURFACE
  DATA ../data/met/{surface_path.name} ISHD
  EXTRACT surface.ext
  QAOUT surface.qa
  XDATES {year}/01/01 TO {year}/12/31
  LOCATION {surface['wban']} {sf_lat} {sf_lon} {TIME_ADJUST} {surface['elevation_m']:.1f}
  AUDIT ALL
UPPERAIR
  DATA ../data/met/{upper_path.name} IGRA
  EXTRACT upperair.ext
  QAOUT upperair.qa
  XDATES {year}/01/01 TO {year}/12/31
  LOCATION {upper['aermet_id']} {ua_lat} {ua_lon} {TIME_ADJUST} {upper['elevation_m']:.1f}
  AUDIT ALL
"""
    deck2 = f"""** Surface characteristics below are explicit illustrative assumptions, not AERSURFACE.
JOB
  MESSAGES aermet2.msg
  REPORT aermet2.rpt
SURFACE
  QAOUT surface.qa
UPPERAIR
  QAOUT upperair.qa
METPREP
  XDATES {year}/01/01 TO {year}/12/31
  NWS_HGT WIND {surface['anemometer_height_m']:.2f}
  METHOD REFLEVEL SUBNWS
  OUTPUT clemson.sfc
  PROFILE clemson.pfl
  FREQ_SECT ANNUAL 1
  SECTOR 1 0 360
  SITE_CHAR 1 1 0.20 1.0 0.10
"""
    write_preserving(project / "aermet" / "aermet1.inp", deck1)
    if minute_winds:
        enhanced = deck2.replace("  QAOUT surface.qa\n", "  QAOUT surface.qa\n  ASOS1MIN ../aerminute/clemson_1min.dat\n")
        if existing_deck.exists() and existing_deck.read_text() == deck2:
            preserve_hourly_baseline(project)
            existing_deck.write_text(enhanced)
        else:
            write_preserving(existing_deck, enhanced)
    else:
        write_preserving(existing_deck, deck2)
    print(f"Prepared {year}: {surface_icao}/{surface['wban']} + {upper['igra_id']}; raw precipitation {precip['status_counts']}")
    return selection


def run_aermet(project: Path, executable: Path,
               aerminute_executable: Path = Path("/workspace/.cloud-setup/amp-plots/bin/aerminute")) -> dict:
    directory = project / "aermet"
    if not executable.is_file():
        raise RuntimeError(f"AERMET executable unavailable: {executable}")
    outputs = [directory / name for name in ("clemson.sfc", "clemson.pfl")]
    enhanced = "ASOS1MIN" in (directory / "aermet2.inp").read_text()
    minute_provenance = None
    if enhanced:
        hourfile = project / "aerminute" / "clemson_1min.dat"
        if not hourfile.exists():
            # The helper requires its saved explicit IFW policy; no station facts are inferred.
            helper = project / "scripts" / "aerminute_inputs.py"
            subprocess.run([sys.executable, str(helper.resolve()), "--project", str(project.resolve()),
                            "run", "--aerminute", str(aerminute_executable.resolve())], check=True)
        provenance_path = project / "aerminute" / "run_provenance.json"
        minute_provenance = json.loads(provenance_path.read_text())
        recorded = [entry for entry in minute_provenance["outputs"] if Path(entry["path"]).name == hourfile.name]
        if minute_provenance["status"] != "passed" or len(recorded) != 1 or recorded[0]["sha256"] != sha256(hourfile):
            raise RuntimeError("AERMINUTE hourly winds lack a successful matching provenance/checksum")
    if any(path.exists() for path in outputs):
        baseline = directory / "hourly_baseline"
        if enhanced and all(path.exists() and (baseline / path.name).exists()
                            and sha256(path) == sha256(baseline / path.name) for path in outputs):
            for name in ("clemson.sfc", "clemson.pfl", "aermet2.msg", "aermet2.rpt", "aermet2.stdout.txt", "aermet2.stderr.txt", "run_provenance.json"):
                path = directory / name
                if path.exists():
                    if sha256(path) != sha256(baseline / name):
                        raise RuntimeError(f"Preserving changed baseline output: {path}")
                    path.unlink()
        else:
            raise RuntimeError("Existing AERMET outputs preserved; inspect or explicitly archive them before a new run")
    commands = []
    ready_stage1 = all((directory / name).exists() for name in ("surface.qa", "upperair.qa", "aermet1.rpt"))
    stages = (2,) if enhanced and ready_stage1 and "AERMET FINISHED SUCCESSFULLY" in (directory / "aermet1.rpt").read_text() else (1, 2)
    for stage in stages:
        command = [str(executable.resolve()), f"aermet{stage}.inp"]
        result = subprocess.run(command, cwd=directory, text=True, capture_output=True)
        write_preserving(directory / f"aermet{stage}.stdout.txt", result.stdout)
        write_preserving(directory / f"aermet{stage}.stderr.txt", result.stderr)
        messages = (directory / f"aermet{stage}.msg").read_text(errors="replace")
        errors = [line for line in messages.splitlines() if re.search(r"\bE\d\d\b", line)]
        commands.append({"command": command, "exit_status": result.returncode, "error_messages": errors})
        if result.returncode != 0 or errors:
            raise RuntimeError(f"AERMET Stage{stage} failed; inspect aermet/aermet{stage}.msg/.rpt")
    if not all(path.is_file() and path.stat().st_size > 0 for path in outputs):
        raise RuntimeError("AERMET produced no populated surface/profile outputs")
    year = json.loads((project / "scenario.json").read_text())["year"]
    quality = audit_surface_output(outputs[0], year)
    result = {"commands": commands, "stage1_reused": stages == (2,), "one_minute_winds": enhanced,
              "outputs": {path.name: sha256(path) for path in outputs},
              "quality_summary": quality,
              "aerminute_provenance_sha256": sha256(project / "aerminute" / "run_provenance.json") if enhanced else None,
              "ifw_status": minute_provenance["inputs"]["ifw"] if minute_provenance else None,
              "note": "AERMET stage execution succeeded. Inspect reports and separate raw precipitation audit before scientific interpretation."}
    write_json(directory / "run_provenance.json", result)
    print("AERMET stages1/2 completed; populated clemson.sfc and clemson.pfl")
    return result


def audit_surface_output(path: Path, year: int) -> dict:
    lines = path.read_text().splitlines()
    rows = [line.split() for line in lines[1:]]
    expected = 24 * (datetime(year + 1, 1, 1) - datetime(year, 1, 1)).days
    keys = []
    counts = Counter()
    wind_sources = Counter()
    for row in rows:
        if len(row) != 27:
            raise RuntimeError("Unexpected modern AERMET surface record structure")
        numeric = list(map(float, row[:25]))
        if not all(math.isfinite(value) for value in numeric):
            raise RuntimeError("AERMET surface output has nonfinite numerical data")
        y, month, day, _, hour = map(int, row[:5])
        if y != year or not 1 <= hour <= 24:
            raise RuntimeError("AERMET surface output has a date outside the selected LST year")
        keys.append((y, month, day, hour))
        wind, direction, ustar, obukhov = numeric[15], numeric[16], numeric[6], numeric[11]
        counts["calm_wind_hours"] += wind == 0
        counts["positive_wind_hours"] += wind > 0
        counts["missing_or_invalid_wind_direction_hours"] += not 0 <= direction <= 360
        counts["positive_friction_velocity_hours"] += ustar > 0
        counts["positive_precipitation_output_hours"] += numeric[21] > 0
        counts["missing_precipitation_output_hours"] += numeric[20] == 99 or numeric[21] < 0
        # A diagnostic only: AERMOD's own valid-hour report is authoritative.
        usable = (wind > 0 and 0 <= direction <= 360 and ustar > 0 and obukhov != -99999
                  and 0 < numeric[18] < 900 and numeric[10] > 0)
        counts["plausibly_usable_hours_before_AERMOD_checks"] += usable
        wind_sources[row[25]] += 1
    if len(rows) != expected or len(set(keys)) != expected:
        raise RuntimeError(f"AERMET output lacks a complete unique hourly LST calendar: {len(rows)}/{expected}")
    required_keys = {(year, (datetime(year, 1, 1) + timedelta(days=d)).month,
                      (datetime(year, 1, 1) + timedelta(days=d)).day, h)
                     for d in range(expected // 24) for h in range(1, 25)}
    if set(keys) != required_keys:
        raise RuntimeError("AERMET output calendar has an unexpected missing or duplicate date")
    return {"year": year, "hourly_records": len(rows), "counts": dict(counts),
            "wind_source_flags": dict(wind_sources),
            "interpretation": "Full hourly calendar retains calm/missing/invalid hours; record count is not usable-hour completeness. AERMOD's report controls actual modeling acceptance."}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", type=Path, default=PROJECT)
    commands = parser.add_subparsers(dest="action", required=True)
    prepare_parser = commands.add_parser("prepare", help="Download/verify observations, audit, and create stage inputs")
    prepare_parser.add_argument("--year", type=int, default=2023)
    prepare_parser.add_argument("--offline", action="store_true", help="Use only checksum-verified retained NOAA files")
    prepare_parser.add_argument("--surface", choices=("KCEU", "KGSP"), default="KCEU", help="Explicit choice; no automatic fallback")
    wind_mode = prepare_parser.add_mutually_exclusive_group()
    wind_mode.add_argument("--minute-winds", action="store_true", default=None, help="Fetch actual one-minute ASOS files and enable AERMINUTE output in Stage2")
    wind_mode.add_argument("--hourly-baseline", action="store_false", dest="minute_winds", help="Prepare hourly-only baseline; never overwrite a different existing deck")
    run_parser = commands.add_parser("run", help="Run both AERMET stages once; preserve pre-existing outputs")
    run_parser.add_argument("--aermet", type=Path, default=Path("/workspace/.cloud-setup/amp-plots/bin/aermet"))
    run_parser.add_argument("--aerminute", type=Path, default=Path("/workspace/.cloud-setup/amp-plots/bin/aerminute"))
    args = parser.parse_args()
    try:
        if args.action == "prepare":
            prepare(args.project, args.year, args.offline, args.surface, args.minute_winds)
        else:
            run_aermet(args.project, args.aermet, args.aerminute)
        return 0
    except (RuntimeError, OSError, ValueError, HTTPError, URLError, zipfile.BadZipFile, subprocess.CalledProcessError) as error:
        print(f"Meteorology blocked: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
