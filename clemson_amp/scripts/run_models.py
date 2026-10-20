#!/usr/bin/env python3
"""Run and audit the native Clemson AERMAP -> AERMET -> AERMOD workflow.

Examples (from the repository root)::

    python3 clemson_amp/scripts/run_models.py --project clemson_amp --aermap
    python3 clemson_amp/scripts/run_models.py --project clemson_amp --aermet
    python3 clemson_amp/scripts/run_models.py --project clemson_amp \
        --case d10_r1050 --metrics concentration --workers 1
    python3 clemson_amp/scripts/run_models.py --project clemson_amp --all
    python3 clemson_amp/scripts/run_models.py --project clemson_amp \
        --all --no-aermap --no-aermet

Existing expected result files are preserved under each run's prior_outputs/
before execution, so an old plot cannot make a failed Fortran STOP 0 look like
a passing run. AERPLOT.exe is an official Windows tool and is never invoked
by this native Linux runner. Use the prepared aerplot.inp files on Windows.
Passing this audit establishes program execution and result structure. It
does not establish meteorological representativeness or scientific validity.
"""

from __future__ import annotations

import argparse
from collections import Counter
import concurrent.futures
import datetime as dt
import hashlib
import json
import math
import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import sys
import time
import uuid

try:
    import fcntl
except ImportError:  # Windows users can run native EPA executables sequentially.
    fcntl = None


METRICS = ("concentration", "dry_deposition", "wet_deposition")
DEFAULT_BIN_DIR = Path("/workspace/.cloud-setup/amp-plots/bin")
FAILURE = re.compile(
    r"Finishes\s+UN[- ]successfully|AERMET\s+FINISHED\s+UN-SUCCESSFULLY|"
    r"Fatal Error Occurred|Fortran runtime error|segmentation fault|ERROR STOP",
    re.IGNORECASE,
)


def utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat()


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def artifact(path: Path, project: Path) -> dict:
    stat = path.stat()
    return {
        "path": os.path.relpath(path, project),
        "bytes": stat.st_size,
        "sha256": sha256(path),
        "mtime_utc": dt.datetime.fromtimestamp(stat.st_mtime, dt.timezone.utc).isoformat(),
    }


def write_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    temporary.replace(path)


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace") if path.is_file() else ""


def tokens(path: Path):
    for line in read_text(path).splitlines():
        if not line.strip() or line.lstrip().startswith(("**", "!", ";", "#")):
            continue
        yield shlex.split(line, comments=False, posix=True)


def deck_dependencies(deck: Path, outputs: list[Path]) -> list[Path]:
    """Hash actual files named by the deck, including included terrain and met."""
    excluded = {p.resolve() for p in outputs}
    found = {deck.resolve()}
    for fields in tokens(deck):
        for field in fields:
            candidate = (deck.parent / field).resolve()
            if candidate.is_file() and candidate not in excluded:
                found.add(candidate)
    return sorted(found)


def explicit_receptors(path: Path) -> list[tuple[float, float]]:
    receptors = []
    for fields in tokens(path):
        if fields and fields[0].upper() == "RE":
            fields = fields[1:]
        if len(fields) >= 3 and fields[0].upper() == "DISCCART":
            receptors.append((float(fields[1]), float(fields[2])))
    return receptors


def aermod_receptors(deck: Path, seen: set[Path] | None = None) -> list[tuple[float, float]]:
    """Count each case's actual explicit receptors, including its RE INCLUDED file."""
    seen = set() if seen is None else seen
    deck = deck.resolve()
    if deck in seen:
        raise ValueError(f"Cyclic receptor include: {deck}")
    if not deck.is_file():
        raise FileNotFoundError(f"Receptor deck/include is missing: {deck}")
    seen.add(deck)
    receptors = explicit_receptors(deck)
    for fields in tokens(deck):
        if len(fields) >= 3 and [word.upper() for word in fields[:2]] == ["RE", "INCLUDED"]:
            receptors.extend(aermod_receptors(deck.parent / fields[2], seen))
    seen.remove(deck)
    return receptors


def configured_plotfiles(deck: Path) -> list[Path]:
    outputs = []
    for fields in tokens(deck):
        if len(fields) >= 3 and [word.upper() for word in fields[:2]] == ["OU", "PLOTFILE"]:
            index = 4 if fields[2].upper() in ("PERIOD", "ANNUAL") else 5
            if len(fields) <= index:
                raise ValueError(f"Incomplete OU PLOTFILE record in {deck}")
            outputs.append(deck.parent / fields[index])
    return list(dict.fromkeys(outputs))


def configured_postfiles(deck: Path) -> list[Path]:
    return [deck.parent / fields[5] for fields in tokens(deck)
            if len(fields) >= 6 and [word.upper() for word in fields[:2]] == ["OU", "POSTFILE"]]


def plot_rows(path: Path) -> list[tuple[float, float, float]]:
    rows = []
    for line in read_text(path).splitlines():
        if not line.strip() or line.lstrip().startswith(("*", "#", "!")):
            continue
        fields = line.split()
        try:
            values = tuple(float(item.replace("D", "E").replace("d", "e")) for item in fields[:3])
        except ValueError:
            continue
        if len(values) != 3 or not all(math.isfinite(x) for x in values):
            raise ValueError(f"Invalid numeric plot row in {path.name}: {line[:120]}")
        rows.append(values)
    return rows


def fatal_counts(text: str) -> list[int]:
    return [int(value) for value in re.findall(
        r"A\s+Total\s+of\s+(\d+)\s+Fatal\s+Error", text, flags=re.IGNORECASE
    )]


def warning_statistics(cwd: Path, reports: list[Path]) -> dict:
    """Keep warnings visible without changing the execution pass/fail policy."""
    by_report = {}
    for report in reports:
        counts = [int(value) for value in re.findall(
            r"A\s+Total\s+of\s+(\d+)\s+Warning\s+Message", read_text(report), re.IGNORECASE
        )]
        if counts:
            by_report[report.name] = counts
    pattern = re.compile(r"^\s*([A-Z]{2})\s+(W\d{3})\b", re.MULTILINE)
    codes: Counter = Counter()
    source = None
    # errors.out lists each event once; the same events appear again in reports.
    for path in [cwd / "errors.out", *reports]:
        matches = pattern.findall(read_text(path))
        if matches:
            codes.update(pathway + code for pathway, code in matches)
            source = path.name
            break
    known_notes = {
        "CNW732": "24-hour concentration average has fewer than 18 valid hours; AERMOD applied its calms policy."
    }
    hours = {}
    for key, wording in (
        ("total_processed_hours", r"Hours\s+Were\s+Processed"),
        ("calm_hours", r"Calm\s+Hours\s+Identified"),
        ("missing_hours", r"Missing\s+Hours\s+Identified"),
    ):
        for report in reports:
            match = re.search(r"A\s+Total\s+of\s+(\d+)\s+" + wording, read_text(report), re.IGNORECASE)
            if match:
                hours[key] = int(match.group(1))
                break
    return {
        "reported_warning_counts": sorted({count for counts in by_report.values() for count in counts}),
        "warning_counts_by_report": by_report,
        "diagnostic_warning_codes": dict(sorted(codes.items())),
        "diagnostic_warning_source": source,
        "warning_notes": {code: known_notes[code] for code in codes if code in known_notes},
        "additional_warning_codes_require_review": sorted(set(codes) - set(known_notes)),
        "hour_statistics": hours,
    }


def expected_outputs(kind: str, cwd: Path) -> list[Path]:
    if kind == "aermod":
        deck = cwd / "aermod.inp"
        return list(dict.fromkeys([cwd / name for name in ("aermod.out", "errors.out", "aermod.sum", "annual.plt")]
                                  + configured_plotfiles(deck) + configured_postfiles(deck)))
    names = {
        "aermap": ["aermap.out", "aermap.rec", "aermap.src"],
        "aermet1": ["aermet1.rpt", "aermet1.msg", "surface.ext", "surface.qa", "upperair.ext", "upperair.qa"],
        "aermet2": ["aermet2.rpt", "aermet2.msg", "clemson.sfc", "clemson.pfl"],
    }[kind]
    return [cwd / name for name in names]


def validate(kind: str, cwd: Path, log: Path, receptor_count: int) -> tuple[list[str], dict]:
    problems = []
    audit: dict = {}
    reports = [cwd / "aermap.out"] if kind == "aermap" else (
        [cwd / f"{kind}.rpt"] if kind.startswith("aermet") else [cwd / "aermod.out", cwd / "aermod.sum"]
    )
    text = "\n".join(read_text(path) for path in [log, *reports])
    component = "AERMET" if kind.startswith("aermet") else kind.upper()
    success = (r"AERMET\s+FINISHED\s+SUCCESSFULLY" if component == "AERMET"
               else rf"{component}\s+Finishes\s+Successfully")
    audit["completion_marker"] = bool(re.search(success, text, re.IGNORECASE))
    if not audit["completion_marker"]:
        problems.append(f"Missing {component} successful-completion marker")
    if FAILURE.search(text):
        problems.append("Model reported unsuccessful completion or a runtime error")
    counts = fatal_counts(text)
    audit["reported_fatal_error_counts"] = counts
    audit.update(warning_statistics(cwd, reports))
    if any(counts):
        problems.append(f"Model report contains nonzero fatal error count: {counts}")
    match = re.search(rf"{component}[^\n]{{0,60}}?(?:VERSION|VER\s*:)\s*(\d{{5}})", text, re.IGNORECASE)
    if not match:
        match = re.search(rf"{component}[^\n]{{0,60}}?\b(\d{{5}})\b", text, re.IGNORECASE)
    audit["reported_version"] = match.group(1) if match else None

    # Error/message files may legitimately be empty; primary reports and data may not.
    optional_empty = {"errors.out", "aermet1.msg", "aermet2.msg"}
    for output in expected_outputs(kind, cwd):
        if not output.is_file():
            problems.append(f"Current run did not create {output.name}")
        elif not output.stat().st_size and output.name not in optional_empty:
            problems.append(f"Current result is empty: {output.name}")

    if kind == "aermap" and (cwd / "aermap.rec").is_file():
        receptors = explicit_receptors(cwd / "aermap.rec")
        audit["receptor_count"] = len(receptors)
        audit["expected_receptor_count"] = receptor_count
        if receptor_count and len(receptors) != receptor_count:
            problems.append("AERMAP receptor output count differs from its input deck")
        missing = re.search(r"(?<!\d)-9999(?:\.0*)?(?!\d)", read_text(cwd / "aermap.rec") + read_text(cwd / "aermap.src"))
        if missing:
            problems.append("AERMAP output includes missing terrain sentinel -9999")
    elif kind == "aermod":
        receptor_count = len(aermod_receptors(cwd / "aermod.inp"))
        audit["expected_receptor_count"] = receptor_count
        audit["plots"] = {}
        for path in configured_plotfiles(cwd / "aermod.inp"):
            name = path.name
            if not path.is_file():
                continue
            try:
                rows = plot_rows(path)
                values = [row[2] for row in rows]
                audit["plots"][name] = {
                    "receptor_rows": len(rows), "minimum": min(values) if values else None,
                    "maximum": max(values) if values else None,
                    "nonzero_rows": sum(value != 0 for value in values),
                }
                if not rows:
                    problems.append(f"No receptor data rows in {name}")
                elif receptor_count and len(rows) != receptor_count:
                    problems.append(f"{name} has {len(rows)} receptor rows; expected {receptor_count}")
                if any(value < 0 for value in values):
                    problems.append(f"Negative concentration/deposition output in {name}")
            except ValueError as exc:
                problems.append(str(exc))
    elif kind == "aermet2":
        surface = read_text(cwd / "clemson.sfc").splitlines()
        profiles = read_text(cwd / "clemson.pfl").splitlines()
        audit.update(surface_data_rows=max(0, len(surface) - 1), profile_data_rows=len(profiles),
                     meteorology_interpretation="Runner structure/completion audit only; inspect met QA and representativeness separately")
        if len(surface) <= 1 or not profiles:
            problems.append("AERMET produced no usable surface/profile data rows")
    return problems, audit


def execute(kind: str, cwd: Path, binary: Path, project: Path, run_dir: Path,
            receptor_count: int, timeout: float | None, scenario: Path) -> dict:
    label = os.path.relpath(cwd, project).replace(os.sep, "__")
    if kind.startswith("aermet"):
        label += "__" + kind
    deck = cwd / (f"{kind}.inp" if kind.startswith("aermet") else f"{kind}.inp")
    result = {
        "id": label, "component": kind, "working_directory": str(cwd),
        "started_utc": utc_now(), "status": "failed", "problems": [],
        "binary": artifact(binary, project),
        "scenario": artifact(scenario, project),
    }
    try:
        if not deck.is_file():
            raise FileNotFoundError(f"Required input deck is missing: {deck}")
        outputs = expected_outputs(kind, cwd)
        inputs = deck_dependencies(deck, outputs)
        if scenario.is_file():
            inputs.append(scenario)
        result["inputs"] = [artifact(path, project) for path in dict.fromkeys(inputs)]
        previous = []
        for output in outputs:
            if output.exists():
                target = run_dir / "prior_outputs" / label / output.name
                target.parent.mkdir(parents=True, exist_ok=True)
                previous.append(dict(artifact(output, project), archived_path=os.path.relpath(target, project)))
                shutil.move(str(output), str(target))
        result["preserved_previous_outputs"] = previous
        command = [str(binary)]
        if kind.startswith("aermet"):
            command.append(deck.name)
        result["command"] = command
        log = run_dir / "logs" / (label + ".log")
        log.parent.mkdir(parents=True, exist_ok=True)
        result["log"] = os.path.relpath(log, project)
        print(f"Running {label}", flush=True)
        started = time.monotonic()
        with log.open("w", encoding="utf-8") as stream:
            try:
                completed = subprocess.run(command, cwd=cwd, stdout=stream, stderr=subprocess.STDOUT,
                                           stdin=subprocess.DEVNULL, timeout=timeout, check=False)
                result["returncode"] = completed.returncode
                if completed.returncode:
                    result["problems"].append(f"Command exit status {completed.returncode}")
            except subprocess.TimeoutExpired:
                result["returncode"] = None
                result["problems"].append(f"Command exceeded timeout {timeout} seconds")
        result["elapsed_seconds"] = round(time.monotonic() - started, 3)
        problems, audit = validate(kind, cwd, log, receptor_count)
        result["problems"].extend(problems)
        result["audit"] = audit
        if any(audit["reported_warning_counts"]) or audit["diagnostic_warning_codes"]:
            print(f"WARNING: {label}: reported warning count(s) {audit['reported_warning_counts']}; "
                  f"codes {audit['diagnostic_warning_codes']}", flush=True)
        if audit["additional_warning_codes_require_review"]:
            print(f"WARNING: {label}: additional model warning codes require review: "
                  + ", ".join(audit["additional_warning_codes_require_review"]), flush=True)
        result["outputs"] = [dict(artifact(path, project), created_by_current_run=True)
                             for path in outputs if path.is_file()]
        if not result["problems"]:
            result["status"] = "passed"
    except (OSError, ValueError) as exc:
        result["problems"].append(str(exc))
    result["finished_utc"] = utc_now()
    write_json(run_dir / "steps" / (label + ".json"), result)
    print(f"{result['status'].upper()}: {label}" + (
        ": " + "; ".join(result["problems"]) if result["problems"] else ""
    ), flush=True)
    return result


def resolve_binary(directory: Path, name: str) -> Path:
    for path in (directory / name, directory / (name + ".exe")):
        if path.is_file() and os.access(path, os.X_OK):
            with path.open("rb") as stream:
                windows_binary = stream.read(2) == b"MZ"
            if windows_binary and os.name != "nt":
                raise ValueError(f"Windows executable cannot run natively here: {path}")
            return path.resolve()
    raise FileNotFoundError(f"Native executable {name} is missing or not executable in {directory}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--project", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--scenario", type=Path,
                        help="Scenario JSON (default: PROJECT/scenario.json); permits isolated case revisions")
    parser.add_argument("--bin-dir", type=Path, default=DEFAULT_BIN_DIR)
    parser.add_argument("--aermap", action=argparse.BooleanOptionalAction, default=None,
                        help="Run terrain preprocessing (enabled by --all unless --no-aermap)")
    parser.add_argument("--aermet", action=argparse.BooleanOptionalAction, default=None,
                        help="Run both AERMET stages (enabled by --all unless --no-aermet)")
    selection = parser.add_mutually_exclusive_group()
    selection.add_argument("--case", action="append", help="Particle case to run; repeat for several cases")
    selection.add_argument("--all", action="store_true", help="Run both preprocessors and every particle case")
    parser.add_argument("--metrics", nargs="+", default=list(METRICS), help="Subset of concentration dry_deposition wet_deposition")
    parser.add_argument("--workers", type=int, choices=(1, 2, 3, 4), default=2, help="Parallel independent case/metric runs, maximum 4")
    parser.add_argument("--timeout-seconds", type=float, default=0, help="Per-command timeout; 0 means no timeout")
    args = parser.parse_args()
    project = args.project.resolve()
    scenario_path = args.scenario.resolve() if args.scenario else project / "scenario.json"
    try:
        scenario = json.loads(scenario_path.read_text(encoding="utf-8"))
        standard_cases = [case["name"] for case in scenario["particle_cases"]]
        diagnostic_cases = [path.name for path in (project / "aermod").glob("diagnostic_*")
                            if path.is_dir() and re.fullmatch(r"diagnostic_[A-Za-z0-9_]+", path.name)
                            and any((path / metric / "aermod.inp").is_file() for metric in METRICS)]
        known_cases = standard_cases + diagnostic_cases
        cases = standard_cases if args.all else list(dict.fromkeys(args.case or []))
        if any(case not in known_cases for case in cases):
            parser.error("Unknown particle case; choose from " + ", ".join(known_cases))
        metrics = list(dict.fromkeys(metric for group in args.metrics for metric in group.split(",")))
        if any(metric not in METRICS for metric in metrics):
            parser.error("Unknown metric; choose from " + ", ".join(METRICS))
        do_map = args.all if args.aermap is None else args.aermap
        do_met = args.all if args.aermet is None else args.aermet
        if not (do_map or do_met or cases):
            parser.error("Select --aermap, --aermet, --case, or --all")
        required = [name for name, selected in (("aermap", do_map), ("aermet", do_met), ("aermod", bool(cases))) if selected]
        binaries = {name: resolve_binary(args.bin_dir.resolve(), name) for name in required}
        if args.timeout_seconds < 0:
            parser.error("--timeout-seconds must be nonnegative")
    except (OSError, ValueError, KeyError) as exc:
        parser.error(str(exc))

    audit_directory = project / "run_manifests"
    audit_directory.mkdir(parents=True, exist_ok=True)
    workflow_lock = (audit_directory / ".workflow.lock").open("a")
    if fcntl is not None:
        try:
            fcntl.flock(workflow_lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            workflow_lock.close()
            parser.error("Another run_models.py process is using this project")
    run_id = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "_" + uuid.uuid4().hex[:8]
    run_dir = project / "run_manifests" / run_id
    run_dir.mkdir(parents=True)
    manifest = {
        "run_id": run_id, "started_utc": utc_now(), "status": "running", "project": str(project),
        "scenario": artifact(scenario_path, project), "cases": cases, "metrics": metrics,
        "parallel_model_workers": args.workers, "steps": [],
        "scope": "Native model execution and output-structure audit; not a scientific or meteorological validation",
        "aerplot": "Official AERPLOT.exe requires Windows and is not invoked by this Linux runner",
    }

    def save():
        write_json(run_dir / "manifest.json", manifest)
        write_json(project / "run_manifests" / "latest.json", manifest)

    save()
    count = len(explicit_receptors(project / "aermap" / "aermap.inp"))
    common = dict(project=project, run_dir=run_dir, receptor_count=count,
                  timeout=args.timeout_seconds or None, scenario=scenario_path)
    try:
        for kind, selected in (("aermap", do_map), ("aermet1", do_met), ("aermet2", do_met)):
            if not selected:
                continue
            component = "aermet" if kind.startswith("aermet") else kind
            result = execute(kind, project / component, binaries[component], **common)
            manifest["steps"].append(result)
            save()
            if result["status"] != "passed":
                raise RuntimeError(f"{kind} failed; dependent model runs were not started")

        if cases:
            prerequisites = [project / "aermap" / name for name in ("aermap.rec", "aermap.src")]
            prerequisites += [project / "aermet" / name for name in ("clemson.sfc", "clemson.pfl")]
            missing = [str(path) for path in prerequisites if not path.is_file() or not path.stat().st_size]
            if missing:
                raise RuntimeError("Preprocessing products missing; run --aermap/--aermet first: " + ", ".join(missing))

        with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as pool:
            pending = {pool.submit(execute, "aermod", project / "aermod" / case / metric,
                                   binaries["aermod"], **common): (case, metric)
                       for case in cases for metric in metrics}
            for future in concurrent.futures.as_completed(pending):
                manifest["steps"].append(future.result())
                save()
        manifest["status"] = "passed" if all(step["status"] == "passed" for step in manifest["steps"]) else "failed"
    except (OSError, ValueError, RuntimeError) as exc:
        manifest["status"] = "failed"
        manifest["error"] = str(exc)
        print(f"FAILED: {exc}", file=sys.stderr)
    except KeyboardInterrupt:
        manifest["status"] = "interrupted"
        manifest["error"] = "Execution interrupted; inspect step logs before resuming"
    finally:
        manifest["finished_utc"] = utc_now()
        save()
        workflow_lock.close()
    print(f"Run {manifest['status']}; audit manifest: {run_dir / 'manifest.json'}", flush=True)
    return 0 if manifest["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
