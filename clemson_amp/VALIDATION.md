# Validation of the Clemson illustrative project

The native EPA workflow passed in this cloud environment. Inputs, data, results,
and assumptions are retained for review; original repository samples are intact.

| Check | Actual result |
|---|---|
| AERMAP 24142 | 1 source, 873 unique receptors; zero fatal errors |
| AERMINUTE 26135 | 12 observed monthly files; 8,760 hourly output records |
| AERMET 26135 | Both stages passed; 8,760 surface and profile records |
| AERMOD full matrix | 15 of 15 full-year jobs passed, each with 873 receptors |
| AERMOD hourly diagnostics | 3 of 3 full-year jobs passed, each with 16 receptors |
| AERMOD fatal errors | Zero in all 18 final jobs |
| AERMOD warnings | Each concentration job has 44 W732 daily-average warnings; deposition jobs have none |
| Model-valid time | 8,063 of 8,760 hours; 390 calm and 307 missing |
| AERPLOT 26135 | 15 input files supplied; Windows executable unrun |

`validation_summary.json` lists every final job, ranges, counts, and its execution
manifest. A separate wet-weather pilot independently verified that PERIOD
deposition equals the sum of hourly deposited amounts and that concentration
is the valid-hour mean. Its earlier hourly-only forcing is distinguished from
the final one-minute-wind runs in `validation/pilot/run_validation.json`.

The **W732 warnings** identify 44 dates with fewer than 18 valid hours for an
optional 24-hour concentration average. The poster plots use PERIOD means and
valid hourly records, not these daily maxima. Keep this limitation if using
`max24h.plt`; do not present those values as complete daily observations.

AERMAP retained the full real elevation tile for hill-height searches. Its two
warnings concern missing TIFF orientation and vertical-unit tags; official tile
metadata confirms north-up rows and metre elevations, consistent with the
defaults. Source ground elevation is 211.44 m. Checks and hashes are recorded
in `aermap/aermap_validation.json`.

AERMINUTE reduced rounded hourly-archive calms from 3,007 to 390 in the final
AERMET product. Sonic/IFW status is an illustrative assumption, not a verified
historical fact. Surface roughness, albedo, and Bowen ratio are declared
assumptions. No weather observations were invented.

The raw precipitation audit retains 26 unknown hours as a separate category.
Weather plots also reject contradictory raw/processed classifications and exact
AERMOD calm/missing flags. The requested calendar window is not a complete
calendar deposition estimate: deposits during excluded hours are not recovered.

Particle comparisons hold emitted mass constant. Concentration is normalized
local dispersion; PERIOD deposition is accumulated g/m². Printed zero can include
values below output precision. The Stokes/shape-factor supplement does not
resolve AMP fibre orientation, polymer degradation, or long-range transport.

Figure scripts verify successful execution records and current hashes for the
source, receptors, weather, scenario, deck, executable, reports, and output.
Stale or unregistered model results are rejected before plotting.
