#!/usr/bin/env python3
"""Verify model-result freshness against run_models.py's persisted audit.

Plotting scripts must call ``verify_model_result`` before reading a model field.
File modification times alone cannot establish that outputs match a scenario.
This helper requires a passed native-model step, its current-run output marker,
and exact hashes of the deck, included source/receptors, SFC/PFL, scenario,
binary, and requested result. Analytical calculations do not need a model run.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
import shlex


class UnverifiedModelResult(ValueError):
    """A result has no passed, current-input execution record."""


def sha256(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def artifact_path(project: Path, item: dict) -> Path:
    value = item.get("path")
    if not isinstance(value, str) or not value:
        raise ValueError("Audit artifact has no path")
    path = Path(value)
    return (path if path.is_absolute() else project / path).resolve()


def verify_artifact(project: Path, item: dict) -> dict:
    path = artifact_path(project, item)
    expected = item.get("sha256", "")
    if not isinstance(expected, str) or not re.fullmatch(r"[a-fA-F0-9]{64}", expected):
        raise ValueError(f"Audit has no SHA-256 for {path}")
    if not path.is_file():
        raise ValueError(f"Audited file is missing: {path}")
    actual = sha256(path)
    if actual != expected.lower():
        raise ValueError(f"File changed after the model run: {path}")
    return {"path": str(path), "sha256": actual, "bytes": path.stat().st_size}


def required_inputs(project: Path, directory: Path) -> set[Path]:
    """Check the four model-file bindings actually named in this study's deck."""
    deck = directory / "aermod.inp"
    required = {deck.resolve(), (project / "scenario.json").resolve()}
    named = {}
    for line in deck.read_text(encoding="utf-8").splitlines():
        if not line.strip() or line.lstrip().startswith(("**", "!", "#", ";")):
            continue
        fields = shlex.split(line)
        if len(fields) < 3:
            continue
        keyword = tuple(value.upper() for value in fields[:2])
        if keyword in {("SO", "INCLUDED"), ("RE", "INCLUDED"),
                       ("ME", "SURFFILE"), ("ME", "PROFFILE")}:
            named[keyword] = (directory / fields[2]).resolve()
    expected = {("SO", "INCLUDED"), ("RE", "INCLUDED"),
                ("ME", "SURFFILE"), ("ME", "PROFFILE")}
    if set(named) != expected:
        raise ValueError("AERMOD deck must identify included source/receptors and SFC/PFL bindings")
    required.update(named.values())
    return required


def matching_steps(project: Path, directory: Path) -> list[tuple]:
    """Find records in completed manifests and individually persisted steps.

    Individual steps are saved before their containing matrix completes. Using
    such a passed step is valid, but a newer failed attempt must not silently
    fall back to an older run with leftover results.
    """
    records = []
    for run_directory in sorted((project / "run_manifests").glob("*")):
        if not run_directory.is_dir():
            continue
        manifest_path = run_directory / "manifest.json"
        files = sorted((run_directory / "steps").glob("*.json"))
        if manifest_path.is_file():
            files.insert(0, manifest_path)
        for record_path in files:
            try:
                document = json.loads(record_path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            steps = document.get("steps", []) if record_path.name == "manifest.json" else [document]
            for step in steps:
                if not isinstance(step, dict) or step.get("component") != "aermod":
                    continue
                working_directory = step.get("working_directory")
                if not isinstance(working_directory, str):
                    continue
                work_path = Path(working_directory)
                work_path = (work_path if work_path.is_absolute() else project / work_path).resolve()
                if work_path != directory:
                    continue
                order = (str(step.get("started_utc", "")), str(step.get("finished_utc", "")),
                         run_directory.name, record_path.name != "manifest.json")
                records.append((order, step, record_path, manifest_path))
    return records


def verify_model_result(project: Path, result_path: Path) -> dict:
    """Return figure provenance only when a native-model output is verified.

    Raises with an actionable rerun message when a model execution is absent,
    unsuccessful, superseded by failure, or stale relative to current inputs.
    SHA-256 comparisons are performed on content rather than timestamps.
    """
    project, result_path = project.resolve(), result_path.resolve()
    directory = result_path.parent
    try:
        records = matching_steps(project, directory)
        if not records:
            raise ValueError("No run_models.py execution record exists for this result directory")
        _, step, record_path, manifest_path = max(records, key=lambda record: record[0])
        if step.get("status") != "passed":
            raise ValueError(f"Latest native-model step status is {step.get('status')!r}")
        if not step.get("audit", {}).get("completion_marker"):
            raise ValueError("Passed step has no successful native-model completion marker")
        if step.get("problems"):
            raise ValueError("Model step reports unresolved execution or validation problems")
        inputs, outputs = step.get("inputs"), step.get("outputs")
        if not isinstance(inputs, list) or not inputs or not isinstance(outputs, list):
            raise ValueError("Native-model audit has no input/output artifact inventory")
        actual_inputs = {artifact_path(project, item) for item in inputs}
        unrecorded = required_inputs(project, directory) - actual_inputs
        if unrecorded:
            raise ValueError("Model run did not hash current required bindings: " + ", ".join(map(str, sorted(unrecorded))))
        checked_inputs = [verify_artifact(project, item) for item in inputs]
        binary = step.get("binary")
        if not isinstance(binary, dict):
            raise ValueError("Native-model audit has no binary identity")
        checked_binary = verify_artifact(project, binary)
        selected = [item for item in outputs if artifact_path(project, item) == result_path]
        if len(selected) != 1:
            raise ValueError("Requested result is not uniquely recorded among this step's outputs")
        if selected[0].get("created_by_current_run") is not True:
            raise ValueError("Requested result has no current-run creation marker")
        checked_output = verify_artifact(project, selected[0])
        checked_reports = []
        for item in outputs:
            if artifact_path(project, item).name in {"aermod.out", "aermod.sum", "errors.out"}:
                if item.get("created_by_current_run") is not True:
                    raise ValueError("Native completion report has no current-run creation marker")
                checked_reports.append(verify_artifact(project, item))
        return {
            "verification": "passed current-run content hashes and model-completion audit",
            "step_id": step.get("id"),
            "started_utc": step.get("started_utc"),
            "finished_utc": step.get("finished_utc"),
            "execution_record": {"path": str(record_path), "sha256": sha256(record_path)},
            "manifest": {"path": str(manifest_path), "sha256": sha256(manifest_path)} if manifest_path.is_file() else None,
            "reported_model_version": step.get("audit", {}).get("reported_version"),
            "inputs": checked_inputs,
            "binary": checked_binary,
            "output": checked_output,
            "completion_reports": checked_reports,
        }
    except (OSError, ValueError, KeyError, TypeError) as exc:
        try:
            case = directory.relative_to(project / "aermod").parts[0]
        except (ValueError, IndexError):
            case = "<particle_case>"
        raise UnverifiedModelResult(
            f"Cannot plot unverified or stale model output {result_path}: {exc}. "
            f"Rerun: python clemson_amp/scripts/run_models.py --project {project} "
            f"--case {case} --metrics {directory.name}; then regenerate figures."
        ) from exc
