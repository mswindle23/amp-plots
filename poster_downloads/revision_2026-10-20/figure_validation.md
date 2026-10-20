# Independent figure validation

Validation performed on 2026-10-20 against native AERMOD outputs and the
original figure provenance, separately from the new plotting implementation.

- The draft revised profile CSV contains **504 rows and 21 series**
  (comparison, particle case, and quantity). Its size row contains exactly
  **0.5, 1, 5, and 10 µm**. The density row retains 10 µm particles at
  0.90, 1.05, and 1.40 g/cm³.
- Every series accounts for all **873 receptors**. Bin membership was checked
  directly against native coordinates. Every bin's receptor count, mean
  radius, arithmetic mean result, and printed-zero receptor count agrees with
  a separate calculation from the native files.
- All **nine retained density-series profiles** agree with the original
  `poster_figures_provenance.json` values, radii, and counts, with absolute
  numerical tolerance 1e-12. The original data were not rescaled.
- All **15 original model outputs** still pass their original 2026-10-19
  execution records, including current input, output, binary, and completion
  report hashes. The original scenario remains unchanged.
- All **six additional size runs** pass current-input execution verification
  with AERMOD26135 and the identical retained weather, source, and receptor
  terrain files. Each requests 8,760 hours, with 390 calm and 307 missing
  hours, leaving **8,063 valid hours**. Both concentration runs have 44 known
  CNW732 warnings about optional 24-hour completeness; all four deposition
  runs have no warnings. The revision uses PERIOD fields, not those optional
  daily statistics. No fatal errors were reported.

An independent Stokes/Cunningham calculation at 1,050 kg/m³ and χ = 1 gives
settling velocities **0.0104830, 0.0367263, 0.8149804, and 3.2083373 mm/s**
at 0.5, 1, 5, and 10 µm. The 0.5 µm Cunningham correction is **1.3283323**.
The revised single-panel theory uses 0.5–10 µm; its maximum Reynolds number
is **0.002837**, at 10 µm, 1,400 kg/m³, and χ = 1. At fixed volume and
density, the implemented shape sensitivity is exactly v(χ) = v(1)/χ. Its
nonspherical slip approximation is explicitly identified; it does not change
χ in AERMOD.

Precision limits materially affect the smallest wet-deposition fields:
0.5 µm has **434 printed-zero receptors**, and 1 µm has **413**. Averaging
rounded values can yield positive bin means below the native 1e-5 g/m²
printing increment; this does not recover additional native precision.
Printed zeros are not evidence of absent deposition or transport. The plot
omits zero means from logarithmic axes while its CSV retains them and their
counts. Direction-averaged receptor means are not area-weighted mass budgets
or trajectories.

Final review passed for all three PNGs: profiles, single-panel theory, and
settling velocity versus χ. The requested sizes, units, χ distinctions,
legends, and precision caveats are legible. The reference-shape points on the
χ plot agree with the source ledger (sphere 1.00, cube 1.08, and cylinders
1.10, 1.35, and 1.68 for the stated aspect ratios). They are labeled as
aerosol reference geometries; film and foam values are explicitly unassigned.
The secondary-source status and limits of morphotype interpretation are
documented in the accompanying literature notes.

The complete final provenance has **nine artifact hashes**, all independently
verified against current files. Final CSV validation repeated the native-bin
and unchanged-density checks. All **3,168 theoretical-settling rows** and
**404 χ-curve rows** independently match the stated Stokes/Cunningham/χ
equation and Reynolds-number expression within relative tolerance 2e-14.
The theory CSV additionally retains the exact requested diameter markers.
