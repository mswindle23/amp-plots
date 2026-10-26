# Independent map review

Review passed for the three final PNG/PDF maps placed on actual USGS geographic context. No AERMOD inputs or results were changed.

- All **6,993 displayed values** (2,331 native receptor cells × three quantities) match a separate direct read of native AERMOD PERIOD files exactly. Deposition is converted from 24-hour accumulated µg/m² to µg/m²/h by division by 24; concentration remains µg/m³.
- All **58 current source, basemap, native-execution, script, and artifact hash bindings** in the map provenance match their current files.
- The basemap GeoTIFF is genuinely **NAD83 / UTM zone 17N (EPSG:26917)**. Its north-up affine transform, 3,000 × 940 pixels, and exact extent agree with the PNG metadata and plotting extent.
- Source E 331435.622 m, N 3839097.591 m transforms to **82.8400000014° W, 34.6800000019° N**. Its registered image position is pixel **(313.0435, 470.0)** measured from the upper left.
- True geographic north is **1.047325° clockwise/right of grid north** at the source. The plotted north arrow uses a GDAL-transformed geographic vector; the 2 km scale bar uses projected model meters.
- Final concentration, dry-deposition, and wet-deposition maps were visually inspected. Roads, Clemson/University labels, imagery, source, wind, scale bar, native 1 km value annotations, contour labels, units, and large poster text remain legible. Attribution is present.
- The visible note identifies rectangular overlay edges as **display limits**, avoiding a false physical transport boundary. Semi-transparent colors blend with the basemap; labeled contours and native-value callouts provide quantitative anchors. Contour positions are cartographic interpolations of the same native grid, while filled 100 m cells retain the exact native values.
- The source and weather remain illustrative; the real basemap provides geographic context rather than model calibration or observed local microplastic concentrations.

Additional field anchors at 1 km projected-grid east:

- concentration: 0.00217885 ug/m3.
- dry_deposition: 0.008325 ug/m2/h.
- wet_deposition: 0.0518758333333 ug/m2/h.

The final geographic-context KMZ also passed independent ZIP CRC and KML XML/resource checks: **31 overlays**, **82,080 native points**, and **all 34 original embedded assets preserved byte-for-byte**. Every overlay bounding box lies in the Clemson region. The additional overlay is the properly warped geographic basemap; modeled PNG bytes were not altered.
