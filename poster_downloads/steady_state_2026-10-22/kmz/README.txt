DIRECT KMZ MAPS — CONTROLLED CLEMSON AERMOD SCENARIOS

Open a .kmz file directly in Google Earth Pro or another KMZ-capable GIS.
The three clemson_u2_rain1 files each show one actual modeled field
at 2 m/s with 1 mm/h rain. The combined file contains all ten wind/rain
cases and all three quantities; its default view is baseline concentration.
Expand a case, select one quantity at a time, and switch other quantities
off. The concentration layer is preselected within each case.

Every quantity includes an interpolated display overlay, units/color
legend, and a separately switchable folder of actual native receptor
values. Click a receptor to inspect its numerical value. Source and
wind-direction markers are included. All modeled images are embedded;
no external overlay image server is required. A basemap may separately
require connectivity in the GIS application.

Concentration: micrograms/m3. Dry/wet deposition: micrograms/m2/hour.
Flux is derived from validated 24-hour accumulation divided by 24
identical valid modeled hours. It is not deposition velocity.
Weather is synthetic and constant. The source and emissions are
illustrative, not a measured local microplastic inventory.

Continuous colors linearly interpolate actual native receptor results
over the refined display grid [-1,10] km alongwind and +/-1 km across
wind; they are not a separate Gaussian-plume calculation. Outside the
display extent, absence of an overlay does not imply zero concentration.
Each metric has one shared positive logarithmic color scale across all
cases. Transparent pixels indicate zero or no display coverage.
Point layers retain actual native values, including zeros.

Georeferencing uses GDAL/PROJ, NAD83 UTM17N to WGS84, and a full
raster warp. KMZs passed GDAL LIBKML direct-open, ZIP CRC, XML, local
resource/style, image-decoding, coordinate-bound and native-result
hash checks. Interactive rendering in Google Earth was not tested.
See kmz_provenance.json and the accompanying workbook/methods.
