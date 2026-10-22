# Controlled steady-state microplastic plumes near Clemson

These are new native AERMOD26135 runs with **fixed weather within every
scenario**, rather than averages over changing observed weather. They use real
terrain near Clemson and an illustrative, constant roadside emissions source.
The source and meteorology are explicit assumptions, not measurements.

**2024 is the regional microplastics reference year.** It is the latest nearby
atmospheric sampling year verified in the targeted literature search. Complete
annual Clemson microplastics data were not verified. Published 2024 observations
from Coweeta, Highlands, and Iron Duff provide regional context, not a local
mass-emission inventory or validation of this hypothetical source. The model's
July 15, 2024 dates label a **synthetic 24-hour experiment**, not observed weather
or a full-calendar hindcast. See [the source and year review](research/README.md).

## Requested scenarios

1. **Constant wind near 2 m/s:** 24 repeated hourly steady-state calculations
   at 2 m/s. Direction, stability, mixing depth, temperature, humidity, rain,
   source, and particle properties remain constant. Rain at 1 mm/h permits dry
   and wet deposition to operate together. A paired no-rain run shows the
   precipitation control. Flux at a fixed receptor is constant; accumulated
   deposition increases linearly. There is no simulated plume arrival time.
2. **Wind-speed comparison:** 1, 2, 3.5, 5, and 7 m/s, covering <2, 2–5, and
   >5 m/s, with both precipitation states. These are selected speeds, not means
   of observed wind-speed bins. The 2 and 5 m/s endpoints belong to the middle
   group. The same source, year, terrain, particle, wind direction, stability,
   temperature, humidity, and mixing depth apply to every speed. Friction
   velocity and the tiny associated heat flux are derived consistently from
   wind speed and therefore change between speed cases; they stay fixed within
   each run. This is a controlled, physically coupled wind sensitivity.
3. **Steady plume maps:** actual AERMOD receptor concentrations and dry/wet
   deposition fluxes, with baseline wind from the west (270 degrees), carrying
   the plume east. PNGs and direct KMZ files are generated from those results.
   Any interpolation is labeled for display; it is not another dispersion model.

Five speeds × two rain states × three separately requested quantities produce
**30 native runs**. Each has 24 valid modeled hours and 2,736 real-terrain
receptors. The full hourly table contains **656,640 scenario–hour–receptor rows**,
with concentration, dry deposition, and wet deposition in separate columns.

## Source and particles

The hypothetical 100 m × 100 m roadside patch is centered at 34.680 N,
82.840 W: E 331435.622 m, N 3839097.591 m, NAD83 / UTM zone 17N.
It emits **10 g/day = 0.00011574074074074075 g/s** continuously, released at
2 m with initial vertical sigma 1 m. The illustrative emissions calculation is:

```
10,000 assumed vehicles/day × 0.1 km assumed contributing segment
× 0.1 g total tire wear/(vehicle km) × 0.10 assumed airborne share
= 10 g/day airborne tire-wear-containing aerosol surrogate.
```

The wear factor and airborne-share assumption are supported by the cited
literature; traffic activity and the contributing segment are scenario choices.
No actual roadway or facility inventory is claimed. The mass represents a
tire-wear-containing composite surrogate, not a measured pure-polymer fraction.
Source strength is deliberately held fixed during rain as well as dry weather;
the runs do not model rainfall suppression of tire-wear emissions.

Particles are **5 µm monodisperse equivalent spheres**, density 1.234 g/cm³,
mass fraction 1, effectively χ = 1. The shape factors discussed for fibers,
films, and fragments were not imposed on these AERMOD runs. Their orientation,
folding, and polymer degradation are unresolved. No additional aerodynamic
density conversion is applied to the supplied numerical diameter.

## Meteorology and terrain

Meteorology is generated directly in the AERMOD SFC/PFL interface. No AERMET
execution or airport observation is claimed for these synthetic records.
Stability is fixed at L = +1,000,000 m, a nearly neutral weak-stable limit.
Mechanical mixing height is 1,000 m, roughness 0.1 m, temperature 293.15 K
at 2 m, humidity 80%, wind reference height 10 m, and direction FROM 270 degrees.
The exact complete fields, missing-value sentinels, pressure, and derived
parameters are recorded in `scenario.json`, the original SFC/PFL files, and the
workbook. Hours use Eastern Standard Time (UTC−5), without daylight-saving shifts.

AERMAP24142 processes the full retained USGS 3DEP tile. The original 873 terrain
receptors are retained, with an additional 1,863 receptors forming a 100 m grid
along the eastward plume through 10 km and ±1 km crosswind. The merged grid has
2,736 unique receptors. Coarser surrounding receptors preserve the original
20 km × 20 km context. Terrain is real; source placement remains hypothetical.

## Units and interpretation

- Concentration: **µg/m³**. PERIOD is the mean across the 24 valid hours.
- Hourly dry/wet deposition: **µg/m² deposited in a one-hour interval**.
  Dividing by one hour gives the numerically identical flux in **µg/m²/h**.
- PERIOD deposition: **µg/m² accumulated over 24 hours**, not a mean flux.
- Both dry and wet depletion operate consistently in all three quantity runs.
  Dry deposition can occur during rain. No-rain wet deposition should be zero.
- Fields represent this source's contribution; no ambient background
  microplastic concentration or deposition is added.
- Each no-rain job reports the expected MXW496 warning that total precipitation
  is zero while wet-deposition physics is enabled. That warning is reviewed as
  part of this intentional control; rainfall jobs should have no warnings.
- `OU FILEFORM EXP` preserves scientific-notation output at this small source
  rate. Physically meaningful small numbers are not rounded away at a fixed
  five-decimal printing floor.

The time-series receptor is 1 km east of the source, selected from actual
terrain receptors. Distance profiles follow the downwind grid rather than
direction-averaged annuli. Receptor samples and plotted fields are not
area-integrated mass budgets. Results are screening sensitivities, not measured
Clemson environmental concentrations or an annual risk estimate.
Here, east follows the projected UTM x-axis. Grid convergence near Clemson is
about one degree; this axis is not exactly geodetic due east. KMZ locations
use the transformed native receptor coordinates.

## Files and verification

- `scenario.json`, `aermet/`, `aermod/`, `aermap/`: complete numerical model inputs.
- `research/`: published observations, references, and source assumptions.
- `scripts/`: input preparation, workbook/figure generation, and KMZ generation.
- `run_manifests/`: actual execution records and content hashes.
- `outputs/` and `deliverables/`: native-result tables, workbook, plots, and maps.

All native model inputs and outputs accompany the download package. The Excel
workbook contains structured input fields, exact input text, every hourly and
PERIOD receptor result, native report text, units, research context, and
verification records. Large binary terrain data and model executables are
identified by source/version and checksums rather than embedded as spreadsheet
cells; their processed numerical terrain inputs are included in full.

KMZ files are self-contained exports of actual AERMOD results and can be opened
directly in Google Earth. They do not imply that the Windows AERPLOT executable
was run in this Linux environment. Earlier study results remain unchanged.

Plot titles, axes, tick labels, and legends use enlarged poster fonts; PNGs are
300 dpi and the matching PDFs retain scalable text. Detailed assumptions are
kept in this document, the workbook, and `METHODS_AND_LIMITATIONS.txt`.

## Reproduce in the retained cloud environment

Python dependency versions are pinned in `requirements.txt`. Native EPA models
are retained under `/workspace/.cloud-setup/amp-plots/bin`. GIS exports also
require the installed GDAL command-line programs (version 3.10.3 here).
Use the existing validated terrain and model products while their hashes match.
For an intentional rerun, preserve the old outputs first. From the repository
root, the sequence is:

```bash
python3 clemson_amp/steady_state_2026-10-22/scripts/prepare_steady.py \
  --terrain-directory clemson_amp/steady_state_2026-10-22/aermap_refined
python3 clemson_amp/scripts/run_models.py \
  --project clemson_amp/steady_state_2026-10-22 \
  --all --no-aermap --no-aermet --workers 4
python3 clemson_amp/steady_state_2026-10-22/scripts/validate_steady.py
python3 clemson_amp/steady_state_2026-10-22/scripts/independent_validate.py
python3 clemson_amp/steady_state_2026-10-22/scripts/build_deliverables.py
python3 clemson_amp/steady_state_2026-10-22/scripts/build_kmz.py
```

If terrain inputs change, regenerate them first using the documented native
workflow in `aermap_refined/README.md`. AERMET is deliberately not rerun for
these engineered meteorological controls. The parent project's verified
observed-weather products and original figures are separate.
