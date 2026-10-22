#!/usr/bin/env python3
"""Run independent native full-tile AERMAP jobs and merge their receptor rows.

Parallelism changes only the division of receptors into native jobs. Every
receptor and the source retains the same full-tile terrain/critical-hill search.
No elevation or critical-hill value is interpolated by Python.
"""
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
import hashlib
import json
import math
import re
import shutil
import subprocess

BASE = Path(__file__).resolve().parent
BINARY = Path('/workspace/.cloud-setup/amp-plots/bin/aermap')
TERRAIN = (BASE / '../../data/terrain/USGS_1_n35w083.tif').resolve()


def now():
    return datetime.now(timezone.utc).isoformat()


def digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def artifact(path):
    return {'path': str(path.resolve()), 'sha256': digest(path),
            'bytes': path.stat().st_size}


def read_receptors(path):
    rows = []
    for line in path.read_text().splitlines():
        fields = line.split()
        if fields and fields[0] == 'DISCCART':
            rows.append((tuple(map(float, fields[1:5])), line))
    return rows


def run_chunk(directory):
    record = directory / 'execution.json'
    audit = {'status': 'running', 'started_utc': now(),
             'working_directory': str(directory), 'binary': artifact(BINARY),
             'input': artifact(directory / 'aermap.inp'),
             'terrain': artifact(directory / 'terrain' / TERRAIN.name)}
    record.write_text(json.dumps(audit, indent=2) + '\n')
    try:
        with (directory / 'aermap.stdout.txt').open('w') as stdout, \
                (directory / 'aermap.stderr.txt').open('w') as stderr:
            run = subprocess.run([str(BINARY)], cwd=directory,
                                 stdout=stdout, stderr=stderr, check=False)
        audit['exit_code'] = run.returncode
        if run.returncode != 0:
            raise RuntimeError(f'AERMAP exited {run.returncode}')
        report = (directory / 'aermap.out').read_text()
        fatal = re.findall(r'A Total of\s+(\d+)\s+Fatal Error', report, re.I)
        warnings = re.findall(r'A Total of\s+(\d+)\s+Warning Message', report, re.I)
        if not fatal or any(int(value) for value in fatal):
            raise RuntimeError('Native fatal-error summary missing or nonzero')
        if 'AERMAP Finishes Successfully' not in report:
            raise RuntimeError('Missing native success marker')
        rows = read_receptors(directory / 'aermap.rec')
        expected = [line.split()[2:4]
                    for line in (directory / 'aermap.inp').read_text().splitlines()
                    if line.split()[:2] == ['RE', 'DISCCART']]
        if len(rows) != len(expected):
            raise RuntimeError('Native receptor count differs from deck')
        if not all(abs(values[0] - float(xy[0])) <= .01 and
                   abs(values[1] - float(xy[1])) <= .01
                   for (values, _), xy in zip(rows, expected)):
            raise RuntimeError('Native receptor coordinates differ from deck')
        if not all(all(math.isfinite(v) for v in values) and
                   values[3] >= values[2] for values, _ in rows):
            raise RuntimeError('Invalid native terrain values')
        audit.update(status='passed', receptor_count=len(rows), fatal_errors=0,
                     warnings=int(warnings[-1]) if warnings else None,
                     warning_codes=sorted(set(re.findall(r'\bW\d{3}\b', report))),
                     completion_marker='AERMAP Finishes Successfully',
                     outputs=[artifact(directory / name) for name in
                              ['aermap.rec', 'aermap.src', 'aermap.out',
                               'aermap.stdout.txt', 'aermap.stderr.txt']])
    except Exception as exc:
        audit.update(status='failed', error=str(exc))
        raise
    finally:
        audit['finished_utc'] = now()
        record.write_text(json.dumps(audit, indent=2) + '\n')
        print(f"{directory.name}: {audit['status']}", flush=True)
    return audit


def main():
    full_deck = BASE / 'aermap.inp'
    lines = full_deck.read_text().splitlines()
    receptor_lines = [line for line in lines
                      if line.split()[:2] == ['RE', 'DISCCART']]
    assert len(receptor_lines) == 2736
    if (BASE / 'chunks').exists():
        raise RuntimeError('Chunks already exist; preserve/archive before intentional rerun')
    record = BASE / 'aermap_validation.json'
    audit = {'status': 'running', 'program': 'AERMAP', 'version': '24142',
             'started_utc': now(), 'method':
             'Four independent official native AERMAP jobs, each using the full verified terrain tile; merged native receptor rows without terrain interpolation.',
             'input': artifact(full_deck), 'binary': artifact(BINARY),
             'terrain': artifact(TERRAIN), 'workers': 4,
             'original_receptor_count': 873, 'new_receptor_count': 1863,
             'expected_receptor_count': 2736, 'steps': []}
    record.write_text(json.dumps(audit, indent=2) + '\n')
    directories = []
    for index in range(4):
        directory = BASE / 'chunks' / f'chunk_{index + 1:02}'
        (directory / 'terrain').mkdir(parents=True)
        shutil.copy2(TERRAIN, directory / 'terrain' / TERRAIN.name)
        if digest(directory / 'terrain' / TERRAIN.name) != audit['terrain']['sha256']:
            raise RuntimeError('Copied terrain failed content hash')
        selected = receptor_lines[index::4]
        chunk_lines = []
        inserted = False
        for line in lines:
            fields = line.split()
            if fields[:2] == ['CO', 'DATAFILE']:
                chunk_lines.append(f'CO DATAFILE terrain/{TERRAIN.name}')
            elif fields[:2] == ['RE', 'DISCCART']:
                if not inserted:
                    chunk_lines.extend(selected)
                    inserted = True
            else:
                chunk_lines.append(line)
        (directory / 'aermap.inp').write_text('\n'.join(chunk_lines) + '\n')
        directories.append(directory)
    try:
        with ThreadPoolExecutor(max_workers=4) as pool:
            futures = [pool.submit(run_chunk, directory) for directory in directories]
            for future in as_completed(futures):
                audit['steps'].append(future.result())
                record.write_text(json.dumps(audit, indent=2) + '\n')
        by_coordinate = {}
        sources = []
        for directory in directories:
            for values, line in read_receptors(directory / 'aermap.rec'):
                if values[:2] in by_coordinate:
                    raise RuntimeError('Duplicate native receptor across chunks')
                by_coordinate[values[:2]] = (values, line)
            source_rows = [line for line in (directory / 'aermap.src').read_text().splitlines()
                           if line.split()[:2] == ['SO', 'LOCATION']]
            if len(source_rows) != 1:
                raise RuntimeError('Missing native source location')
            sources.append(source_rows[0])
        if len(set(sources)) != 1:
            raise RuntimeError('Native source results disagree across chunks')
        source_elevation = float(sources[0].split()[-1])
        if abs(source_elevation - 211.44) > .01:
            raise RuntimeError('Native source elevation differs from original')
        rows = sorted(by_coordinate.values(), key=lambda item: (item[0][1], item[0][0]))
        expected = [tuple(map(float, line.split()[2:4])) for line in receptor_lines]
        if len(rows) != len(expected) or not all(
                abs(row[0] - point[0]) <= .01 and abs(row[1] - point[1]) <= .01
                for (row, _), point in zip(rows, expected)):
            raise RuntimeError('Merged native receptor inventory differs from full deck')
        merged_lines = ['** AERMAP24142: merged authentic native receptor rows from four full-tile jobs.',
                        '** Each receptor and source was processed against the entire verified USGS tile.',
                        '** See chunks/chunk_*/execution.json and aermap_validation.json for native execution proof.',
                        '** 2736 receptors: original873 plus1863 fine-grid receptors.',
                        'RE ELEVUNIT METERS']
        merged_lines.extend(line for _, line in rows)
        (BASE / 'aermap.rec').write_text('\n'.join(merged_lines) + '\n')
        shutil.copy2(directories[0] / 'aermap.src', BASE / 'aermap.src')
        original = read_receptors(BASE / '../../aermap/aermap.rec')
        comparisons = []
        for values, _ in original:
            merged, _ = by_coordinate[values[:2]]
            comparisons.append(max(abs(a - b) for a, b in zip(values, merged)))
        if len(comparisons) != 873 or max(comparisons) > .01:
            raise RuntimeError('Retained original terrain values differ')
        audit.update(status='passed', finished_utc=now(), receptor_count=len(rows),
                     unique_receptor_count=len(by_coordinate), source_elevation_m=source_elevation,
                     all_coordinates_match_input_within_m=.01,
                     all_values_finite=True, all_hill_heights_at_least_receptor_elevation=True,
                     original_873_native_values_max_difference_m=max(comparisons),
                     elevation_range_m=[min(v[0][2] for v in rows), max(v[0][2] for v in rows)],
                     hill_height_range_m=[min(v[0][3] for v in rows), max(v[0][3] for v in rows)],
                     outputs=[artifact(BASE / 'aermap.rec'), artifact(BASE / 'aermap.src')])
        (BASE / 'aermap.out').write_text(
            'Composite audit only; actual native AERMAP reports are chunks/chunk_*/aermap.out.\n'
            'All four native full-tile jobs finished successfully with zero fatal errors.\n'
            f'Merged receptor count: {len(rows)}\n')
        audit['outputs'].append(artifact(BASE / 'aermap.out'))
        record.write_text(json.dumps(audit, indent=2) + '\n')
        print(json.dumps({k: audit[k] for k in
                          ['status', 'receptor_count', 'source_elevation_m',
                           'original_873_native_values_max_difference_m',
                           'started_utc', 'finished_utc']}, indent=2), flush=True)
    except Exception as exc:
        audit.update(status='failed', finished_utc=now(), error=str(exc))
        record.write_text(json.dumps(audit, indent=2) + '\n')
        raise


if __name__ == '__main__':
    main()
