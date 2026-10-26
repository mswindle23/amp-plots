# Poster figure revision — October 20, 2026

This revision adds **0.5, 1, 5, and 10 µm** size comparisons to the distance
profiles, a single-panel settling figure, and a settling-velocity versus dynamic
shape-factor χ figure. The original figures and original scenario remain intact.

The original 1 and 10 µm and density-comparison outputs are reused. The two
additional sizes required six new native AERMOD jobs using the exact same
retained 2023 weather, terrain, source, and receptor grid. No size curves were
interpolated from the original results.

Files in `figures/`:

- `particle_distance_profiles_v2.pdf` and `.png`: size row at 0.5/1/5/10 µm;
  original density row at 10 µm. Companion CSV contains the actual annular data.
- `theoretical_settling_v2.pdf` and `.png`: one panel, settling velocity against
  diameter, with χ = 1, 2, and 3 sensitivities and the original three densities.
- `settling_velocity_vs_chi.pdf` and `.png`: fixed-volume settling at 10 µm and
  1.05 g/cm³, with documented shape-factor comparisons. Read the literature
  ledger before treating a comparison as representative of a morphotype.
- `revision_figures_provenance.json`: model execution verification, source,
  weather, native output, script, and rendered-artifact hashes.

[The plot-specific text file](particle_distance_profiles_v2_data_description.txt)
describes the particles, χ, location, dates, weather, source normalization,
outputs, units, binning, and limitations. The shape-factor ledger and literature
notes distinguish published findings from geometric proxies and assumptions.

The dynamic shape-factor figures are separate analytical calculations. The
AERMOD profiles use spherical surrogates (χ = 1); they do not model fibers or
films. Equal mass emission is hypothetical, normalized to 1 g/s.

[Settling figure methods — formatted PDF](settling_figures_methods.pdf) presents
the complete [original methods text](settling_figures_methods.txt) with equations,
constants and reference-geometry tables, and clickable DOI references. The
scientific content and original revision date are preserved. The PDF is available
separately from the original revision ZIP. Regenerate it with
`python clemson_amp/scripts/settling_methods_pdf.py` (requires ReportLab;
rendered with version 4.4.9).

Regenerate the new results only when necessary, from the repository root:

```bash
python3 clemson_amp/scripts/model_inputs.py \
  --scenario clemson_amp/revisions/2026-10-20/scenario_particle_sizes.json \
  --base-dir clemson_amp
python3 clemson_amp/scripts/run_models.py --project clemson_amp \
  --scenario clemson_amp/revisions/2026-10-20/scenario_particle_sizes.json \
  --case d0p5_r1050 --case d05_r1050 --workers 4
python3 clemson_amp/scripts/revision_figures.py --project clemson_amp
```

Unchanged terrain and meteorology need no rerun. The plot generator checks
successful native execution records and current content hashes for all six
unique particle cases and three metrics. All 873 receptor values contribute to
the exported annular table. Use the PDFs for poster layout and the PNGs for
previewing. Downloadable copies are published under the repository's
`poster_downloads/revision_2026-10-20/` folder.
