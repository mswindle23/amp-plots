# Refined native terrain processing

The steady wind is from the west, so the eastward plume needs finer receptors
than the original outer 1 km grid. The final grid merges all **873 original
receptors** with a 100 m grid spanning source-relative east coordinates
−1,000 to +10,000 m and north coordinates −1,000 to +1,000 m. Duplicates are
removed, giving **2,736 unique receptors** (1,863 additions). The original
outer domain is retained.

Coordinates use NAD83 / UTM zone 17N (EPSG:26917), with center
E 331435.622 m, N 3839097.591 m. The hypothetical source southwest vertex
is E 331385.622 m, N 3839047.591 m; its geometry is unchanged.

`run_parallel.py` divides the receptor inventory into four native AERMAP24142
jobs. Every job uses a byte-verified copy of the **entire** USGS 3DEP
1-arcsecond `USGS_1_n35w083.tif` tile, with native terrain extraction and
full-tile critical-hill processing. The four jobs run concurrently; their
authentic native `DISCCART` rows are then merged by coordinate. No terrain
elevation or hill height is calculated or interpolated by Python.

- `aermap.inp` is the complete 2,736-receptor input recipe. Running this one
  deck natively would process the same receptors serially.
- `chunks/chunk_01` through `chunk_04` contain the **actual executed** input
  decks, native reports, receptor/source outputs, and execution records.
- `aermap.rec` contains the merged native rows; `aermap.src` is the first
  native source output after checking identical source results in all four
  jobs. Coordinates are rounded to centimeters by native AERMAP.
- `aermap_validation.json` records native success markers, zero-fatal-error
  checks, count/uniqueness checks, complete input/raster/binary/output hashes,
  and comparison with the original 873 native terrain rows.
- The root `aermap.out` is explicitly a composite audit summary. The actual
  native reports are in the four chunk folders.

Each native run reports the known USGS-tile warnings W450 (missing TIFF
orientation tag; native default is used) and W473 (elevation units default to
meters). These are the same documented warnings as the original validated
tile processing. The GeoTIFF and official tile metadata establish the units.

The initial single-process preparation was intentionally interrupted to
replace it with the equivalent concurrent jobs. Its partial files and audit
are preserved under `interrupted_single_run/`; none supplies final terrain
values. The original project terrain outputs were not modified.

The verified terrain copies and native index files are excluded from Git.
The shared raster must exist at `../../data/terrain/USGS_1_n35w083.tif`.
The runner protects existing chunk directories; preserve/archive outputs
before an intentional rerun. Both the raster retrieval metadata and original
native terrain validation remain in the parent project.
