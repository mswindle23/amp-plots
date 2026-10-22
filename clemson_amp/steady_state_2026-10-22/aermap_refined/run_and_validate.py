#!/usr/bin/env python3
"""Execute official AERMAP on the fine steady-plume grid and audit its outputs."""
from pathlib import Path
from datetime import datetime, timezone
import hashlib, json, math, re, subprocess, sys

BASE = Path(__file__).resolve().parent
REPO = BASE.parents[2]
BINARY = Path('/workspace/.cloud-setup/amp-plots/bin/aermap')
TERRAIN = (BASE/'../../data/terrain/USGS_1_n35w083.tif').resolve()

def digest(path):
    with path.open('rb') as stream: return hashlib.file_digest(stream,'sha256').hexdigest()

def artifact(path):
    return {'path':str(path),'sha256':digest(path),'bytes':path.stat().st_size}

def now(): return datetime.now(timezone.utc).isoformat()

audit={'status':'running','program':'AERMAP','version':'24142','started_utc':now(),
       'working_directory':str(BASE),'binary':artifact(BINARY),'input':artifact(BASE/'aermap.inp'),
       'terrain':artifact(TERRAIN),'method':'Native full-tile terrain and critical-hill processing; original 873 receptors plus fine 100m eastward grid',
       'problems':[]}
record=BASE/'aermap_validation.json'
if '--validate-only' in sys.argv:
    previous=json.loads(record.read_text())
    audit['native_execution_started_utc']=previous.get('native_execution_started_utc',previous.get('started_utc'))
    audit['native_exit_code']=previous.get('exit_code',previous.get('native_exit_code'))
    if audit['native_exit_code'] != 0: raise RuntimeError('No prior zero-exit native execution recorded')
    audit['validation_correction']='Use actual official marker AERMAP Finishes Successfully rather than an AERMOD-style phrase.'
record.write_text(json.dumps(audit,indent=2)+'\n')
try:
    if '--validate-only' not in sys.argv:
        for name in ['aermap.rec','aermap.src','aermap.out']:
            if (BASE/name).exists(): raise RuntimeError(f'Protected existing output {name}; archive explicitly before intentional rerun.')
        with (BASE/'aermap.stdout.txt').open('w') as stdout, (BASE/'aermap.stderr.txt').open('w') as stderr:
            run=subprocess.run([str(BINARY)],cwd=BASE,stdout=stdout,stderr=stderr,check=False)
        audit['exit_code']=run.returncode
        if run.returncode: raise RuntimeError(f'AERMAP exited {run.returncode}')
    else:
        audit['exit_code']=audit['native_exit_code']
    report=(BASE/'aermap.out').read_text(errors='replace')
    errors=re.findall(r'A Total of\s+(\d+)\s+Fatal Error',report,re.I)
    if errors and any(int(v) for v in errors): raise RuntimeError('Fatal native errors reported')
    if not re.search(r'AERMAP Finishes Successfully',report,re.I): raise RuntimeError('Missing native success marker')
    expected=[]
    for line in (BASE/'aermap.inp').read_text().splitlines():
        f=line.split()
        if f[:2]==['RE','DISCCART']: expected.append(tuple(map(float,f[2:4])))
    receptors=[]
    for line in (BASE/'aermap.rec').read_text().splitlines():
        f=line.split()
        if f and f[0]=='DISCCART': receptors.append(tuple(map(float,f[1:5])))
    if len(receptors)!=2736 or len(receptors)!=len(expected): raise RuntimeError('Unexpected receptor count')
    if len({row[:2] for row in receptors})!=len(receptors): raise RuntimeError('Duplicate receptors')
    if not all(all(math.isfinite(v) for v in row) for row in receptors): raise RuntimeError('Nonfinite terrain values')
    if not all(abs(row[0]-xy[0])<=.01 and abs(row[1]-xy[1])<=.01 for row,xy in zip(receptors,expected)): raise RuntimeError('Coordinates differ from input')
    if not all(row[3]>=row[2] for row in receptors): raise RuntimeError('Critical hill below receptor')
    audit.update(status='passed',completion_marker='AERMAP Finishes Successfully',receptor_count=len(receptors),unique_receptor_count=len(receptors),
      all_coordinates_match_input_within_m=.01,all_values_finite=True,all_hill_heights_at_least_receptor_elevation=True,
      elevation_range_m=[min(v[2] for v in receptors),max(v[2] for v in receptors)],hill_height_range_m=[min(v[3] for v in receptors),max(v[3] for v in receptors)],
      original_receptor_count=873,new_receptor_count=1863,
      outputs=[artifact(BASE/name) for name in ['aermap.rec','aermap.src','aermap.out','aermap.stdout.txt','aermap.stderr.txt']])
    source=(BASE/'aermap.src').read_text()
    rows=[line.split() for line in source.splitlines() if line.split()[:2]==['SO','LOCATION']]
    if len(rows)!=1 or abs(float(rows[0][-1])-211.44)>.01: raise RuntimeError('Source elevation differs from validated original')
    audit['source_elevation_m']=float(rows[0][-1])
except Exception as exc:
    audit['status']='failed'; audit['problems'].append(str(exc)); raise
finally:
    audit['finished_utc']=now(); record.write_text(json.dumps(audit,indent=2)+'\n'); print(json.dumps({k:audit.get(k) for k in ['status','receptor_count','source_elevation_m','problems','started_utc','finished_utc']},indent=2),flush=True)
