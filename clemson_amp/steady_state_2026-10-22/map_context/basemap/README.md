# Actual geographic basemap

`usgs_topo.png` is an actual geographic map assembled from the official **USGS
US Topo Clemson and Five Forks, South Carolina, 2024 editions**. It includes
roads, road names, geographic labels, water, and orthophotographic context.
It is not a generated illustration. The edition dates are not asserted to be
the acquisition dates of the underlying imagery or geographic features.

`basemap_metadata.json` records the official source URLs, download sizes and
SHA256 hashes, map footprints, original PDF geotransforms, actual output
extent, renderer and GIS versions, attribution, and final image hash.
`usgs_topo.pgw` supplies a matching world file.

The two official geospatial PDFs were independently rasterized using PyMuPDF
1.26.6 at 200 dpi. GDAL 3.10.3 supplied each PDF's original georeference. The
same-size raster was attached to that exact affine transform, clipped to the
official quadrangle footprint to remove the map collar, mosaiced, and warped
to **NAD83 / UTM zone 17N (EPSG:26917)**. The final 3000 × 940 image covers
E 330235.622–341735.622 m, N 3837297.591–3840897.591 m. No roads or other
geographic features were invented or positioned by eye.

The final raster has 56 transparent subpixel seam samples out of 2,820,000
pixels, documented in metadata. Those tiny cartographic seams do not change
any modeled receptor value. Downstream plots can place white behind them.

Direct USGS/Esri map-service requests were unavailable through the running
network policy, so the supported USGS product API and its official S3 map
downloads supplied the basemap. This uses the same trusted public map source,
without a proxy or an invented replacement map.

Reproduce into a separate directory to preserve an already published map:

```bash
python3 fetch_basemap.py --output /tmp/clemson_basemap_reproduction \
  --source-directory . --offline
```

Omit `--offline` to download missing original PDFs from the recorded official
URLs. The helper deliberately verifies their expected identities. The two raw
PDFs total approximately 107 MB; portable poster packages include the cropped
map and source metadata rather than duplicating those large downloads.

Attribution: **USGS The National Map / US Topo (Clemson and Five Forks,
2024 editions).** The existing AERMOD plume is a separate, hypothetical-source,
synthetic-weather calculation. A map backdrop does not turn it into measured
environmental microplastic concentrations.
