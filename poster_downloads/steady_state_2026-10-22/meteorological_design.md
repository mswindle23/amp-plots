# Controlled meteorology design

These are engineered AERMOD steady-state control experiments. The SFC/PFL
files are generated directly by `scripts/prepare_steady.py`; they are **not
observed weather and were not produced by an AERMET execution**. AERMOD's
automatic output header prints the interface's AERMET version identifier;
that identifier does not establish that AERMET was run.

The date label is July 15, 2024, hours ending 01–24, Eastern Standard Time
(UTC−5). It provides a common calendar identifier for every experiment.
The selection of a microplastic data reference year does not make the
synthetic forcing an observed day in that year.

Five reference winds are modeled: 1, 2, 3.5, 5, and 7 m/s at 10 m above
ground. They represent the requested groups <2, 2–5, and >5 m/s, respectively;
2, 3.5, and 5 m/s all belong to the middle group. These are selected controlled
points, not averages of observed wind-bin populations. Each wind is paired
with zero rain and with 1 mm/h liquid rain, giving ten meteorological cases.
Three native jobs per case request concentration, dry deposition, and wet
deposition, with dry and wet plume depletion enabled in all jobs.

Within each case, every meteorological input is numerically identical for
all 24 hours. The resulting hourly fields must therefore repeat. This
simulates a stationary plume maintained continuously, not an advancing puff,
plume startup, or a cumulative-deposition transient. Hourly deposition is a
constant flux in each experiment; cumulative deposition increases linearly.

Shared externally prescribed conditions:

| Parameter | Value |
|---|---:|
| Wind FROM direction | 270° (plume toward east) |
| Wind reference height | 10 m |
| Monin–Obukhov length, L | +1,000,000 m |
| Mechanical mixing height | 1,000 m |
| Roughness length | 0.10 m |
| Temperature at 2 m | 293.15 K (20 °C) |
| Relative humidity | 80% |
| Surface pressure | 989 hPa |
| Cloud cover | 10 tenths |
| Bowen ratio | 1.0 |
| Albedo | 0.20 |
| Profile base above mean sea level | 211.44 m |

The positive, very large L is a **fixed near-neutral, weak-stable limit**.
AERMOD uses that continuous stability parameter, rather than a user-specified
Pasquill class. L is kept unchanged across the entire matrix. It is not
described as exactly neutral or as measured local stability.

Friction velocity and the tiny negative sensible heat flux are calculated
consistently for each chosen wind:

```
u_star = k * u_ref / [ln(z_ref/z0) + 5 * (z_ref - z0)/L]
H = -rho_air * cp * T_air * u_star^3 / (k * g * L)
```

Constants are k = 0.4, rho_air = 1.2 kg/m³, cp = 1004 J/(kg K), and
g = 9.80616 m/s². Thus these two **derived** quantities change across wind
speeds; they remain constant across hours and across the two rain states at
each speed. The speed comparison is a controlled, physically coupled wind
and turbulence experiment. It does not claim that changing speed leaves
every internal model turbulence quantity unchanged.

The PFL supplies one top-of-profile level at 10 m, with the case's wind speed
and direction. Its temperature is 19.9216 °C, applying the dry-adiabatic
0.0098 K/m adjustment from the 2 m reference. AERMOD constructs the remaining
vertical profiles using the prescribed surface scaling parameters.
Sigma-theta and sigma-w use the supported missing value 99, requesting
model-derived turbulence. Unstable-only WSTAR, upper mixing-height potential
temperature gradient, and convective mixing height use the standard stable
sentinels −9, −9, and −999; they are not missing required stable-regime data.

IPCODE 11 denotes liquid rain and PRATE is 1 mm/h; the paired control uses
IPCODE 0 and PRATE 0. Dry deposition may occur during rain. The rain-case
dry and wet outputs describe competing removal from the same plume, while
the zero-rain case provides a separate dry-weather control.
Keeping wet-depletion physics enabled for those intentional zero-rain controls
produces one native MXW496 warning per job: total precipitation is zero while
wet deposition is selected. This warning is reviewed and expected only for
the zero-rain cases; it is not a missing-rain report. Rain cases must have no
such warning. The validation checks this exact conditional warning pattern.

Synthetic station identifiers 99999/99999999 deliberately avoid assigning
these records to KCEU or another observation station. The header's VERSION
26135 denotes file-interface compatibility. The supported PROG-Mod flag
marks generated input; the adjacent SYNTHETIC label and this note explicitly
describe its origin.

Native concentration is in µg/m³. DEPOUNIT is 3.6×10⁹, so a one-hour native
deposition amount is in µg/m² and is numerically the mean flux in µg/m²/h
over that hour. PERIOD deposition is accumulated µg/m² over all 24 valid
hours; it is not itself a flux. PERIOD concentration is the mean. EXP output
format preserves small values using native E13.6 scientific notation.
The conventional native filename `annual.plt` contains this **24-hour PERIOD**
field; its filename does not make the result an annual mean or annual total.

Real terrain is supplied separately by AERMAP. Source geometry, particle
properties, and emissions remain identical across all ten cases. The source
and meteorology are assumptions; the model fields are predictions for those
assumptions, not measured microplastic concentrations or deposition rates.
