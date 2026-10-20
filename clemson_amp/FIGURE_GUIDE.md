# Figures for the AAAR poster

For the requested **0.5, 1, 5, and 10 µm** profiles and revised settling
figures, use the [October 20 revision](revisions/2026-10-20/README.md).
The figures described below are the preserved original versions.

These figures illustrate the abstract's theoretical questions using a hypothetical
100 m × 100 m source near Clemson and actual 2023 meteorology. The total mass
emission is normalized to **1 g/s in every particle case**. None of the plotted
concentrations, deposition amounts, or source emissions is an environmental AMP
measurement. Equal emitted mass also means unequal emitted particle numbers.
For another constant total emission rate Q, with identical source geometry,
particle properties, and weather, these linear model fields scale by
Q / (1 g/s); this does not supply an empirical emission estimate.

Use the PDF versions in `figures/` for poster layout; matching PNGs are 300 dpi.
Start with the size comparison, settling calculation, and weather comparison.
The density maps and distance profiles provide supporting sensitivity results.
Keep the assumptions and colorbars with any panel used in the poster.

| File stem, with `.pdf` or `.png` | Suggested caption and interpretation |
| --- | --- |
| `particle_size_maps` | **Particle-size sensitivity near Clemson.** AERMOD PERIOD-mean concentration (µg/m³), accumulated dry deposition (g/m²), and accumulated wet deposition (g/m²) for 1, 10, and 30 µm equivalent spheres at 1.05 g/cm³, under identical meteorology and equal normalized mass emission. Each square is a computed receptor; colors share one scale within each row. The source is hypothetical. |
| `particle_density_maps` | **Density sensitivity at fixed particle size.** The same outputs for 10 µm equivalent spheres with densities 0.90, 1.05, and 1.40 g/cm³. Concentration patterns change less across this density range than across the selected 1–30 µm size range; those ranges are study choices, not a universal ranking of particle properties. |
| `particle_distance_profiles` | **Concentration and deposition by distance annulus.** Arithmetic means over the computed receptors in each annulus, with identical weather and equal mass emissions. These directional sample averages are neither plume trajectories nor area-integrated mass budgets. The nested grid uses 100 m inner spacing and 1 km outer spacing. |
| `theoretical_settling` | **Analytical settling sensitivity.** Stokes settling with Cunningham slip correction for equivalent spheres, using the constants in the verified AERMOD VDP1 formulation. Markers identify 1, 10, and 30 µm. The dashed χ = 2 curve divides spherical settling speed by two as a schematic shape-factor illustration. It is a separate calculation, **not an AERMOD fibre/film simulation**. |
| `meteorological_context` | **Meteorological context for the illustrative simulation.** Wind direction is the direction the wind comes FROM. Wind and stability counts use 8,063 valid modeled noncalm hours; stability is defined by the sign of Monin–Obukhov length. Monthly precipitation sums use available, raw-coverage-consistent processed surface records and exclude 31 unknown or discordant hours across the calendar year. |
| `wind_conditioned_receptor_profiles` | **Descriptive wind-speed groups.** Mean hourly concentration and dry/wet deposition flux at 0.5, 1, 5, and 10 km, selecting the nearest downwind cardinal receptor each hour. Selection can miss the true downwind bearing by up to 45°. Weather groups differ in stability, direction, and rainfall; these associations do not isolate a causal wind effect. |
| `stability_precipitation_comparison` | **Weather-associated differences at 1 km.** For the 10 µm, 1.05 g/cm³ case, bars show mean hourly values at the nearest downwind cardinal receptor. Concentrations are grouped by wind speed and stability. Deposition fluxes are grouped by reported precipitation, with trace separate. Counts show the modeled hours in each group. Unknown and raw/processed-discordant precipitation are excluded. |

Actual results that can be stated carefully:

- Across the 36 receptors in the 5–6 km annulus, mean concentration was
  **0.210, 0.101, and 0.0105 µg/m³** for the 1, 10, and 30 µm cases at
  1.05 g/cm³. This supports a larger local airborne concentration footprint for
  smaller spheres in this particular normalized scenario; it does not establish
  long-range travel distances or particle residence times.
- At 10 µm, the same annular means were **0.111, 0.101, and 0.0832 µg/m³**
  as density increased from 0.90 to 1.05 to 1.40 g/cm³. Increased density also
  changes competing dry removal and wet deposition; do not assume every output
  increases with density.
- The 10 µm diagnostic has **3,849 hours below 2 m/s, 3,746 hours at
  2–<5 m/s, and 468 hours at ≥5 m/s**. At the nearest downwind 1 km receptor,
  mean concentrations were **17.3, 2.61, and 1.22 µg/m³**, respectively. These
  results do **not** demonstrate that stronger winds increased a
  concentration-defined transport radius. The observed groups contain different
  combinations of stability, wind direction, and rainfall.
- The resolved-rainfall groups show higher mean wet deposition flux for
  precipitation above 1 mm/h than for 0–1 mm/h. This reflects the model's
  scavenging calculation under the grouped weather, and is not independent field
  validation of AMP wet removal. Dry deposition also occurs during wet hours.
- At density 1.05 g/cm³, the analytical spherical settling speeds are
  **0.0367, 3.21, and 28.6 mm/s** for 1, 10, and 30 µm, respectively. All
  listed 1–30 µm sphere cases have Reynolds number below 0.1. This supports the
  low-Reynolds-number sphere approximation; it does not validate irregular
  microplastic morphology or the illustrative χ = 2 correction.

The 2023 request covers 8,760 hours. AERMOD identified **390 calm and 307 missing
hours**, leaving **8,063 valid hours**. Native hourly POSTFILEs contain zero
records for skipped hours; the plotting scripts exclude the exact I440/I460
timestamps and verify their counts against `aermod.sum`. Rainfall comparisons
retain **8,039** valid hours and exclude **24** unknown or discordant
precipitation hours among the valid modeled hours. These are different scopes
from the 31 excluded precipitation hours across all surface records.

Concentration is a mean over valid noncalm hours. **PERIOD deposition is the sum
of processed one-hour deposits, in g/m²**, not a mean flux and not a complete
calendar-year deposition estimate for the excluded weather. Hourly diagnostic
deposition is the mass per area deposited in one hour, numerically equal to that
hour's mean flux in g/m²/h. Optional 24-hour concentration outputs generated
44 W732 completeness warnings in each concentration run; the figures here do
not use those 24-hour statistics.

Grey map squares are zeros **at the file's printed precision**, which can also
represent positive values below the fixed-format rounding resolution. Log plots
omit zero-valued results. The 1 µm wet-deposition field especially reaches this
precision limit. Do not interpret grey squares as absence of environmental AMP.

The meteorology uses an airport/regional sounding surrogate and illustrative
surface characteristics; AERMINUTE improves wind sampling, but its post-2009
IFW/sonic status setting is an explicit assumption rather than a verified local
commissioning date. The particle model uses equivalent-sphere inputs and does
not resolve fibre orientation, degradation, fragmentation, or transport beyond
the modeled receptor domain. The numerical sphere diameter is passed directly
to the code's density-dependent formula; do not additionally density-convert it
to an aerodynamic diameter while retaining polymer density.

`poster_figures_provenance.json` and `weather_figures_provenance.json` record
the figure hashes, current scenario and input hashes, binary identity, passed
native execution records, exact time filters, and numerical summaries. The
scripts reject stale model outputs. Supporting tables are
`theoretical_settling.csv` and `weather_conditioned_hourly_diagnostics.csv`.
Regenerate after rerunning any changed model inputs:

```bash
python clemson_amp/scripts/poster_figures.py --project clemson_amp
python clemson_amp/scripts/weather_figures.py --project clemson_amp
```
