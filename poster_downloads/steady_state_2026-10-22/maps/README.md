# AERMOD plume on an actual geographic map

The new PNG/PDF figures place the existing computed plume over official USGS
topographic maps with real aerial context, roads, water features, and place
names. The source marker is still **hypothetical**, and the plume is simulated.
No model inputs or numerical AERMOD results were changed for this map view.

The baseline is the same controlled 2 m/s wind, 1 mm/h rain scenario: a
10 g/day roadside aerosol surrogate, 5 µm equivalent spheres, density
1.234 g/cm³, and χ = 1. Concentration is in µg/m³. Dry and wet deposition
maps show flux in µg/m²/h, derived from the verified 24-hour deposition totals.
The July 15, 2024 date labels synthetic steady weather, not observed conditions.

Separate maps show concentration, dry-deposition flux, and wet-deposition flux.
They retain large poster fonts and include a scale bar, north arrow, units,
source marker, and a numerical annotation at the actual receptor 1 km downwind.
The PNG/PDF maps use computed 100 m receptor cells; any contour interpolation
is only a visual summary of those values. Semi-transparent colors let the
geographic background remain visible. Refer to the quantitative legend and
annotated values, rather than sampling colors blended with the map background.

The new KMZ embeds the same geographic background beneath the original
verified model layers. It opens with baseline concentration selected and
retains all wind/rain cases, native receptor values, and layer controls.
Its original viridis palette and shared comparison scales are preserved;
the new PNG/PDF maps use plasma with a separate scale for each baseline
quantity to distinguish the plume from green land cover. Numerical values
are identical; match quantities and read each legend when comparing views.
The KMZ model overlays have approximately 50% effective opacity so that
roads remain visible beneath them; this changes display transparency only.

Basemap: **USGS US Topo, Clemson and Five Forks quadrangles, 2024 editions**,
downloaded through The National Map. The map edition is not a claim that all
underlying aerial imagery or road data were collected in 2024. Full product
URLs, publication dates, retrieval checksums, native georeferencing, and render
details are recorded in `basemap/basemap_metadata.json` and associated records.
The original GeoPDFs retain the underlying map-credit information.

The basemap is cropped/mosaicked in NAD83 / UTM zone 17N (EPSG:26917), matching
the model coordinates. The KMZ background is fully reprojected to a regular
WGS84 raster with GDAL. Transforming only its corner coordinates would not
provide the same georeferencing. The north arrow distinguishes geodetic north
from the slightly rotated UTM grid. No color outside the view should be
interpreted as proof that the modeled source has no contribution there.

Reproduce the map figures after retrieving the audited basemap:

```bash
python3 clemson_amp/steady_state_2026-10-22/scripts/map_plume_on_basemap.py
python3 clemson_amp/steady_state_2026-10-22/scripts/build_map_context_kmz.py
```

Model inputs, the complete Excel workbook, and original native outputs remain
in the earlier controlled-scenario package. These additional geographic views
are delivered separately so that the verified original files stay unchanged.
