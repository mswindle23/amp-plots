# Illustrative Clemson airborne microplastic study

The [October 22 controlled plume scenarios](steady_state_2026-10-22/README.md)
use fixed weather, a literature-based illustrative roadside source, and a
refined terrain grid. They include an Excel workbook, large-font poster plots,
and direct KMZ maps. These controlled runs are separate from the original
observed-weather comparisons below.

The [October 20 figure revision](revisions/2026-10-20/README.md) adds
0.5/1/5/10 µm distance profiles, a single-panel settling figure, and a
velocity–χ figure with plot-specific methods and documented literature limits.

This project adapts the repository's EPA sample inputs to the poster abstract
**A Theoretical Study on Transport and Deposition of Airborne Microplastics**.
The original sample files in the repository root remain unchanged.

The source is hypothetical. Its total release is normalized to **1 g/s of AMP
mass**, not an estimate of a real source's emissions. The results are suitable
for comparing the specified theoretical cases; they do not establish measured
AMP concentrations around Clemson. To scale to a proposed constant mass release
`Q` in g/s, multiply concentrations and deposition fluxes by `Q / 1 g/s`.

## Scenario and comparisons

The source center is approximately **34.680 N, 82.840 W**, near Clemson, South
Carolina. The model uses NAD83 / UTM zone 17N (EPSG:26917), full projected
coordinates, a 100 m by 100 m area source, and a 2 m release height. Its flux is
`1 g/s / 10,000 m² = 0.0001 g/(s m²)`. No existing facility is identified as an
AMP emitter.

There are 873 unique receptors: a 1 km grid across a 20 km by 20 km domain and
a 100 m grid within 1 km of the source, merged without duplicates. All cases
use the same real terrain and observed 2023 weather.

| Case | Numerical particle diameter (µm) | Density (g/cm³) | Comparison |
|---|---:|---:|---|
| `d01_r1050` | 1 | 1.05 | Small-particle sensitivity |
| `d10_r1050` | 10 | 1.05 | Common baseline |
| `d30_r1050` | 30 | 1.05 | Larger-particle sensitivity |
| `d10_r0900` | 10 | 0.90 | Lower-density sensitivity |
| `d10_r1400` | 10 | 1.40 | Higher-density sensitivity |

Each case is monodisperse with mass fraction 1. The cases hold **emitted mass**
constant; they do not hold emitted particle number constant. These are spherical
surrogates, not measured size distributions or identified polymer samples.

The full year 2023 provides seasonal variation in wind, stability, and
precipitation.

Separate AERMOD inputs request concentration, dry deposition, and wet deposition.
**Both dry and wet depletion remain enabled in every case**, so the three
quantities describe the same removal assumptions. Separate outputs also avoid
ambiguous multi-quantity columns when using AERPLOT.

## Real data and explicit assumptions

- **Terrain:** USGS 3DEP 1 arcsecond (approximately 30 m), tile
  `USGS_1_n35w083.tif`, distributed by EPA in its August 2024 collection. This is
  an uncompressed, NAD83 GeoTIFF. The collection label is not a measurement
  date. The entire tile is retained for AERMAP's terrain and critical-hill
  calculations. Provenance and SHA256 hashes are in
  `data/terrain/terrain_provenance.json`.
- **Surface meteorology:** Clemson–Oconee County Regional Airport, **KCEU**,
  USAF **723118**, WBAN **53850**, approximately 34.672 N, 82.881 W, elevation
  270.8 m. NOAA's fixed-width ISD/ISHD observations supply the surface input.
  Wind measurement height is 7.92 m, from EPA's AERMET station table.
  The 2023 observation records report 272 m, which AERMET uses in preference
  to inventory elevation; AERMOD's profile base is therefore set to 272 m.
  **AERMINUTE 26135** processes twelve real monthly one-minute ASOS files;
  AERMET uses those winds with its supported hourly-observation fallback.
  The sonic-anemometer status is an explicitly documented **IFW assumption**
  effective 2023-01-01 for processing, not a verified installation date. The
  station's actual sensor history remains unverified; confirm it for a
  definitive study. This is an illustrative processing assumption, not a
  finding that a particular guide exception applies to KCEU. Input and execution
  provenance and a clarification are retained in `aerminute/`.
- **Upper-air meteorology:** Peachtree City, Georgia, IGRA station
  **USM00072215**, approximately 33.3558 N, 84.5672 W, elevation 244.9 m.
  NOAA's **IGRA** soundings replace the old FSL archive. This station is distant
  from Clemson; its soundings do not resolve local foothill meteorology.
- **Time:** 2023, in **Eastern Standard Time throughout the year**, not daylight
  saving time. The UTC-to-local-standard-time adjustment is 5 hours. Boundary
  observations are fetched so local end-of-year hours are not truncated.
- **Surface characteristics:** albedo 0.20, Bowen ratio 1.0, and roughness length
  0.10 m are illustrative assumptions, held constant across cases. They are not
  derived from an AERSURFACE land-cover assessment. No on-site turbulence data
  or AERSURFACE land-cover processing is claimed.

Read the generated meteorological selection, quality, and validation JSON files
under `data/met/` before interpreting wet deposition or weather comparisons.
Missing precipitation reports must not be classified as observed dry hours.

## Files and model versions

- `scenario.json`: central source, geometry, particle, and station parameters.
- `aermap/aermap.inp`: terrain preprocessing and source/receptor elevations.
- `aermet/aermet1.inp`, `aermet/aermet2.inp`: current two-stage meteorological
  processing using ISHD surface data and IGRA soundings.
- `aerminute/aerminute.inp`: observed one-minute wind preprocessing, including
  the explicit sensor-status assumption recorded in its provenance.
- `aermod/<case>/<quantity>/aermod.inp`: five particle cases and three quantities.
- `aerplot/<case>/<quantity>/aerplot.inp`: matching headless AERPLOT settings,
  full UTM zone 17 coordinates, and quantity labels.
- `scripts/`: repeatable data preparation, input generation, model execution,
  and scientific plotting tools.

The inputs target **AERMAP 24142, AERMET 26135, AERMOD 26135, and AERPLOT
26135**. The repository's old AERMET user guide describes a different workflow;
use the current EPA guide linked below for these inputs. In particular, current
AERMET requires upper-air station elevation on the LOCATION card.

Native Linux AERMAP, AERMET, and AERMOD have been built from unmodified official
EPA source in this cloud environment. AERPLOT 26135 is distributed as a Windows
executable and has not been run on Linux. The supplied AERPLOT inputs can be used
with that executable on Windows; the Python plotting tool supplies a separate
route to poster figures from actual AERMOD outputs.

## Reproduce the workflow

Run commands from the repository root, `/workspace/amp-plots` in this cloud task.
The workflow uses Python 3.11 or later. Plotting additionally
uses the packages pinned in `requirements.txt`.

```bash
python3 clemson_amp/scripts/fetch_terrain.py
python3 clemson_amp/scripts/met_inputs.py prepare --year 2023 --minute-winds
python3 clemson_amp/scripts/aerminute_inputs.py --project clemson_amp prepare --ifw-date 2023-01-01 --assume-ifw
python3 clemson_amp/scripts/met_inputs.py run
python3 clemson_amp/scripts/model_inputs.py
python3 clemson_amp/scripts/run_models.py --aermap
python3 clemson_amp/scripts/model_inputs.py --diagnostics-only
python3 clemson_amp/scripts/run_models.py --all --no-aermap --no-aermet --workers 4
python3 clemson_amp/scripts/run_models.py --case diagnostic_d10_r1050
python3 clemson_amp/scripts/model_inputs.py --aerplot-common-scale
python3 clemson_amp/scripts/poster_figures.py --project clemson_amp
python3 clemson_amp/scripts/weather_figures.py --project clemson_amp
```

The retained data and validated outputs already exist in this cloud environment;
do not rerun preprocessing just to inspect a figure. `prepare --offline` verifies
the retained meteorological cache. The meteorological runner protects existing
outputs; for an intentional rerun, `run_models.py --aermet` archives previous
products first. AERMAP's full-tile run takes about eight minutes, so reuse its
validated products while its input deck and terrain remain unchanged.

Model programs write into their own working directories; relative paths in the
input files assume those directories.
Downloaded archives, rasters, meteorological records, and generated products are
ignored by Git. Retain the provenance JSON alongside your inputs when sharing
the study.

For another machine, place the matching native model programs in a directory and
pass `--bin-dir /path/to/models` to `run_models.py`. The meteorological helper
accepts `--aermet /path/to/aermet` and `--aerminute /path/to/aerminute`. On Windows,
use the corresponding `.exe` paths. Plotting dependencies can be installed into
a Python virtual environment with `pip install -r clemson_amp/requirements.txt`.

To use **AERPLOT on Windows**, first generate the AERMOD results, then change to,
for example, `clemson_amp/aerplot/d10_r1050/concentration` and run the AERPLOT
executable by its full path. Repeat in a different case/quantity directory as
needed. Each directory supplies its own `aerplot.inp`, pointing to that case's
`annual.plt`. Automatic Google Earth launch is disabled; open the resulting KMZ
manually if desired. This Windows execution has not been validated here.

The supplied AERPLOT configurations use shared, zero-safe linear scales across
particle cases: concentration 0–500 µg/m³, accumulated dry deposition 0–600 g/m²,
and accumulated wet deposition 0–3 g/m². These limits were derived from the
verified results. `--aerplot-common-scale` recalculates them after a model rerun
and saves `aerplot/common_scale_provenance.json`. The Python maps use shared
positive-value logarithmic scales to display the wide numerical range.

## Interpret the poster figures

Seven figure sets are available as 300-dpi PNG and PDF files in `figures/`.
Start with `particle_size_maps.pdf`, `particle_density_maps.pdf`, and
`theoretical_settling.pdf`; the weather figures add descriptive comparisons.
`FIGURE_GUIDE.md` supplies suggested captions, actual findings, and limits.
The PDFs are suitable for placement in a poster layout.

All 15 full-year particle/quantity jobs and all three hourly diagnostic jobs
completed without fatal errors. Each concentration job reports 44 known warnings
about optional 24-hour averages with fewer than 18 valid hours. The poster
figures use PERIOD means and valid hourly results. See `VALIDATION.md` and
`validation_summary.json` for the actual checks and limitations.

To adapt the templates, change `scenario.json` and regenerate the model inputs.
The generator overwrites the files it creates under `clemson_amp`; keep manual
experiments in separate copies. Changing latitude/longitude alone does not
reproject the source: update the matching UTM coordinates as well. A new date
range or location also needs matching meteorology and terrain.

| Input section | What it controls here |
|---|---|
| AERMOD `CO` | Concentration or deposition output and removal options |
| AERMOD `SO` | Source flux, dimensions, release height, particle diameter/density |
| AERMOD `RE` | Receptor elevations and hill heights supplied by AERMAP |
| AERMOD `ME` | AERMET output files, station identifiers, profile base, dates |
| AERMOD `OU` | PERIOD results, one-hour maxima, and diagnostic hourly files |
| AERMET `SURFACE` / `UPPERAIR` | `ISHD` observations and modern `IGRA` soundings |
| AERMAP `DATAFILE` | The real USGS elevation raster |
| AERPLOT `PlotFileName` / `origin` | Matching result file and full UTM coordinate origin |

- Concentration is in **µg/m³** for the normalized 1 g/s source. PERIOD dry and
  wet deposition are **accumulated mass per area in g/m²** over the modeled
  period. One-hour deposition records are mass per area deposited during that
  hour, numerically equivalent to that hour's mean flux in g/(m² hour).
- `annual.plt` is a PERIOD mean for concentration and a PERIOD total for
  deposition. The filename alone does not determine its units. `max1h.plt`
  contains independent per-receptor maxima; concentration runs additionally
  produce `max24h.plt`. These do not form one simultaneous plume snapshot.
  Twenty-four-hour deposition output is deliberately omitted because the
  version 26135 single-quantity short-term averaging code has different
  behavior from its PERIOD accumulation.
- A PERIOD concentration mean excludes calm and missing model hours. PERIOD
  deposition sums the processed one-hour deposits. Requesting a calendar year
  does not recover deposition during excluded hours; read the model's actual
  calm/missing/processed-hour counts before calling a map an annual estimate.
- The density and size comparisons use identical weather and geometry. Weather
  comparisons describe the observed conditions; differences in correlated wind,
  stability, precipitation, and wind direction do not isolate a causal effect.
- AERMOD's steady-state formulation supports local dispersion/deposition in this
  domain. It does not establish long-range transport distances, polymer
  degradation, fragmentation, or explicitly resolved fiber/film aerodynamics.
  A separate Stokes-law calculation illustrates settling and shape-factor
  sensitivity; it is not a shape-resolved AERMOD simulation.
- The AERMOD guide calls PARTDIAM a mass-mean aerodynamic diameter, while the
  version 26135 particle-settling code uses the supplied diameter and density in
  a Stokes-plus-slip expression. Here the numerical sizes are documented as
  equivalent spherical inputs. Do not apply another density conversion to the
  diameter and then supply polymer density again. Relating these inputs to
  measured nonspherical AMP requires a separate justified characterization.
- A small source-centered domain cannot capture all emitted mass. Do not
  interpret deposition summed over these nonuniformly spaced receptors as a
  domain mass balance.

## Authoritative sources

- [EPA AERMOD models and current documentation](https://www.epa.gov/scram/air-quality-dispersion-modeling-preferred-and-recommended-models)
- [EPA AERMET 26135 user guide](https://gaftp.epa.gov/Air/aqmg/SCRAM/models/met/aermet/aermet_userguide.pdf)
- [EPA AERMAP user guide](https://gaftp.epa.gov/Air/aqmg/SCRAM/models/related/aermap/aermap_userguide.pdf)
- [EPA distribution of the USGS terrain tile](https://gaftp.epa.gov/Air/aqmg/3dep/08-2024/1_arcsecond/USGS_1_n35w083.zip)
- [NOAA ISD station inventory](https://www.ncei.noaa.gov/pub/data/noaa/isd-history.csv)
- [NOAA IGRA station inventory](https://www.ncei.noaa.gov/pub/data/igra/igra2-station-list.txt)
- [EPA AERPLOT distribution information](https://gaftp.epa.gov/Air/aqmg/SCRAM/models/related/aerplot/aerplot_readme.txt)
