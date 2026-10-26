# Download the Clemson AMP poster files

Use GitHub's **Download raw file** button after opening a ZIP or PDF below.
For the entire branch, select **Code → Download ZIP** on the repository page.

The supplied **original distance-profile figure now has 22-point axis titles**
and colorblind-friendly colors, distinct markers, and distinct line styles:

- [Updated particle-distance profiles (PNG)](revision_2026-10-23/particle_distance_profiles_accessible.png)
- [Updated particle-distance profiles (vector PDF)](revision_2026-10-23/particle_distance_profiles_accessible.pdf)
- [Styling details, exact numerical data, and verification](revision_2026-10-23/)

The **plume on an actual USGS map** is now available, showing real roads,
water, place names, and Clemson University beneath the unchanged model results:

- [Concentration plume on the map (PNG)](steady_state_2026-10-22/maps/clemson_aermod_concentration_on_map.png)
- [Poster version (PDF)](steady_state_2026-10-22/maps/clemson_aermod_concentration_on_map.pdf)
- [Google Earth KMZ with the map background embedded](steady_state_2026-10-22/maps/clemson_plume_on_usgs_map.kmz)
- [All three mapped quantities, source metadata, and checks (ZIP)](clemson_plume_on_map.zip)
- [Dry/wet deposition maps and supporting files](steady_state_2026-10-22/maps/)

These are the same controlled steady-state results. The marked source is
hypothetical; the basemap provides real geographic context.

The **October 22 controlled steady-state scenarios** use a common 2024
regional microplastics reference year and fixed synthetic weather:

- [Excel workbook: all model inputs and receptor outputs](steady_state_2026-10-22/clemson_steady_state_inputs_outputs.xlsx)
- [Complete inputs, native results, workbook, plots, and KMZ package (ZIP)](clemson_steady_state_2026-10-22.zip)
- [Direct KMZ: all ten weather cases and all three output quantities](steady_state_2026-10-22/kmz/clemson_steady_all_scenarios.kmz)
- [Direct KMZ: baseline concentration plume](steady_state_2026-10-22/kmz/clemson_u2_rain1_concentration.kmz)
- [Direct KMZ: baseline dry-deposition flux](steady_state_2026-10-22/kmz/clemson_u2_rain1_dry_deposition.kmz)
- [Direct KMZ: baseline wet-deposition flux](steady_state_2026-10-22/kmz/clemson_u2_rain1_wet_deposition.kmz)
- [PNG: deposition flux through time](steady_state_2026-10-22/figures/deposition_flux_vs_time.png)
- [PNG: flux versus wind speed](steady_state_2026-10-22/figures/deposition_flux_vs_wind_speed.png)
- [PNG: flux versus downwind distance](steady_state_2026-10-22/figures/deposition_flux_vs_distance.png)
- [PNG: actual steady-state plume maps](steady_state_2026-10-22/figures/steady_state_plume_maps.png)
- [Methods and limitations](steady_state_2026-10-22/METHODS_AND_LIMITATIONS.txt) · [All scenario files](steady_state_2026-10-22/)

The workbook includes 656,640 hourly scenario–receptor rows with concentration,
dry deposition, and wet deposition in separate columns, plus all PERIOD and
maximum one-hour receptor values. Constant forcing gives constant flux and
linear accumulated deposition. The year is regional context; these are not
observed-weather or complete annual Clemson microplastics measurements.

The **October 20 figure revision** is available separately:

- [Revised figures, numerical data, methods, and native model results (ZIP)](clemson_amp_figure_revision_2026-10-20.zip)
- [Distance profiles: 0.5, 1, 5, and 10 µm (PDF)](revision_2026-10-20/figures/particle_distance_profiles_v2.pdf)
- [Single-panel settling with χ sensitivity (PDF)](revision_2026-10-20/figures/theoretical_settling_v2.pdf)
- [Settling velocity versus dynamic shape factor χ (PDF)](revision_2026-10-20/figures/settling_velocity_vs_chi.pdf)
- [Data used for the revised distance profiles (text)](revision_2026-10-20/particle_distance_profiles_v2_data_description.txt)
- [Settling calculations and shape-factor sources (text)](revision_2026-10-20/settling_figures_methods.txt)
- [Settling calculations and shape-factor sources (formatted PDF)](revision_2026-10-20/settling_figures_methods.pdf)
- [Revision notes and supporting files](revision_2026-10-20/)

The original downloads remain available:

- [Complete package: inputs, processed data, model results and figures](clemson_amp_poster_package.zip) (6.7 MB)
- [Input files, scripts and instructions](clemson_inputs.zip) (163 KB)
- [Seven figure sets and caption guide](clemson_figures.zip) (2.9 MB)

Individual poster figures:

- [Particle-size maps (PDF)](figures/particle_size_maps.pdf)
- [Particle-density maps (PDF)](figures/particle_density_maps.pdf)
- [Settling theory (PDF)](figures/theoretical_settling.pdf)
- [Particle-distance profiles (PDF)](figures/particle_distance_profiles.pdf)
- [Weather context (PDF)](figures/meteorological_context.pdf)
- [Wind comparisons (PDF)](figures/wind_conditioned_receptor_profiles.pdf)
- [Stability and precipitation comparisons (PDF)](figures/stability_precipitation_comparison.pdf)

[Run instructions and assumptions](../clemson_amp/README.md) ·
[Figure captions and findings](../clemson_amp/FIGURE_GUIDE.md) ·
[Validation report](../clemson_amp/VALIDATION.md)

These are illustrative, normalized 1 g/s source cases using observed 2023 weather
and real terrain near Clemson. The 18 final AERMOD jobs passed without fatal
errors. Concentration runs have documented optional daily-average warnings.
AERPLOT configurations are supplied; the Windows program was not run in cloud.
Raw download archives and model executables are excluded from these compact
packages; data-source URLs, retrieval scripts and provenance are included.
