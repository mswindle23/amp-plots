# Larger labels and accessible distance-profile colors

This restyles the supplied original six-panel figure, preserving its **1, 10,
and 30 µm** size comparison and **0.9, 1.05, and 1.4 g/cm³** density comparison.

- [PNG, 300 dpi](particle_distance_profiles_accessible.png)
- [Vector PDF for poster layout](particle_distance_profiles_accessible.pdf)
- [Exact plotted values (CSV)](particle_distance_profiles_accessible_data.csv)
- [Data and styling provenance (JSON)](particle_distance_profiles_accessible_provenance.json)

Axis titles are **22 points**, matching the recent poster figures. Tick labels
are 18 points, legends 16 points, panel titles 22 points, and the figure title
27 points. The larger canvas accommodates the enlarged labels.

The palette uses blue `#0072B2`, vermilion `#D55E00`, and reddish purple
`#CC79A7` from [Okabe and Ito's Color Universal Design](https://jfly.uni-koeln.de/color/).
Circle/square/triangle markers and solid/dashed/dotted lines provide additional
ways to identify each curve, including in grayscale. Series styles are consistent
across all three columns.

All 15 native AERMOD output files retain their original hashes; all 18 plotted
series (432 annulus means and associated radii/counts) exactly match the original
figure provenance. This is the original observed-2023-weather, equal-1-g/s-emission
sensitivity study near Clemson, not the later controlled 24-hour scenario.
Concentration is a period mean in µg/m³; deposition is a period accumulation in
g/m². Zero means remain gaps on logarithmic axes. No models were rerun.

Reproduce from the repository root with the original model files and provenance:

```sh
python clemson_amp/scripts/accessible_distance_profiles.py
```

The [reproduction script](../../clemson_amp/scripts/accessible_distance_profiles.py)
verifies the native runs, input/output hashes, and exact profile equality before
exporting. The original files and October 20 size revision remain available.
