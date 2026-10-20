# Shape-factor literature checks for the October 20 revision

No universally typical dynamic shape factor (chi) for each environmental
microplastic morphotype was established by the sources inspected. This is a
limited, targeted literature check, not proof that no additional measurements
exist. Avoid presenting illustrative geometry values as measured fiber,
fragment, film, or foam population means.

The plotted numbers in `morphotype_shape_factors.json` are published aerosol
**reference geometries**: sphere 1.00; cube 1.08; average-orientation cylinders
with length/diameter ratios 2, 5, and 10: 1.10, 1.35, and 1.68, respectively.
They are verified in the Hinds-cited Particula implementation at immutable commit
`acf38253e09e8f629bd5e2e93f3aa3a875e5cbd6`:

<https://github.com/uncscode/particula/blob/acf38253e09e8f629bd5e2e93f3aa3a875e5cbd6/particula/particles/properties/aerodynamic_size.py>

The source calls the cylinder entries `cylinder_avg_aspect_2`,
`cylinder_avg_aspect_5`, and `cylinder_avg_aspect_10` and cites Hinds,
*Aerosol Technology*, second edition. Its original textbook table was not
independently accessed. Treat this as verified **secondary** support. These are
not microplastic-specific empirical constants. Do not silently substitute talc
(also listed in the code) for a plastic film.

## Relevant microplastic studies inspected

1. **Tatsii, D.; Bucci, S.; Bhowmick, T.; Guettler, J.; Bakels, L.; Bagheri,
   G.; Stohl, A. (2024). Shape Matters: Long-Range Transport of Microplastic
   Fibers in the Atmosphere. Environmental Science & Technology 58(1),
   671–682.** DOI: <https://doi.org/10.1021/acs.est.3c08209>.
   Full text: <https://pmc.ncbi.nlm.nih.gov/articles/PMC10785798/>.
   Full XML was retrieved from
   <https://www.ebi.ac.uk/europepmc/webservices/rest/PMC10785798/fullTextXML>
   on 2026-10-20.

   This is direct atmospheric microplastic settling evidence. Printed straight,
   semicircular, and quarter-circular fibers had lengths of 500, 1000, and
   2000 micrometers and aspect ratios 20, 50, and 100. Transport-model examples
   used density 1220 kg/m3 and volume-equivalent diameter 75 micrometers.
   The Results state that measured fiber terminal velocities were
   "only 24–51% of the velocities of spheres with the same volume."
   Straight fibers had the smallest velocities, and orientation mattered.
   The drag model uses flatness, elongation, Reynolds number, density ratio,
   and orientation. It does **not** establish a single constant dynamic chi
   for each microplastic morphotype. Do not take reciprocal velocity ratios
   from these larger, finite-Reynolds-number particles and relabel them as
   Stokes chi values for the 0.5–10 micrometer illustrative calculation.

2. **Foroutan, H. (2026). A Model for Dry Deposition of Atmospheric Micro-
   and Nanoplastic Fibers. Environmental Science & Technology Letters
   13(5), 737–743.** DOI: <https://doi.org/10.1021/acs.estlett.6c00165>.
   Full text: <https://pmc.ncbi.nlm.nih.gov/articles/PMC13173645/>.
   XML retrieved from
   <https://www.ebi.ac.uk/europepmc/webservices/rest/PMC13173645/fullTextXML>.

   This paper predates the current project revision. It treats rigid
   cylinders, explicitly omits flexibility and orientation dynamics, and
   models several deposition mechanisms. Its gravitational drag relation
   uses an Aschenbrenner-based shape descriptor for Reynolds numbers 1–300;
   its nanofiber treatment uses anisotropic drag tensors. It compares aspect
   ratios 1, 10, and 100, not a universal dynamic-chi table by morphotype.
   In particular, its aspect ratio is not the dynamic chi used on the new
   plot's horizontal axis. Total dry deposition velocity is not synonymous
   with gravitational settling velocity.

3. **Hernández-Fernández, J.; Puello-Polo, E.; Castro-Suarez, J. R. (2023).
   Characterization of the Morphological and Chemical Profile of Different
   Families of Microplastics in Samples of Breathable Air. Molecules
   28(3), 1042.** DOI: <https://doi.org/10.3390/molecules28031042>.
   Full text: <https://pmc.ncbi.nlm.nih.gov/articles/PMC9919819/>.
   XML retrieved from
   <https://www.ebi.ac.uk/europepmc/webservices/rest/PMC9919819/fullTextXML>.

   This study defines a dynamic shape factor in its aerodynamic-diameter
   discussion but its measured morphology table reports sphericity,
   compactness, roundness, ellipse ratio, and related image descriptors.
   Those numerical descriptors are not dynamic chi and were not used as
   chi values in the figure.

4. **Preston, C. A.; McKenna Neuman, C. L.; Aherne, J. (2023). Effects of
   Shape and Size on Microplastic Atmospheric Settling Velocity.
   Environmental Science & Technology 57(32), 11937–11947.** DOI:
   <https://doi.org/10.1021/acs.est.3c03671>.
   Metadata and abstract verified through Crossref and Europe PMC
   (PubMed 37523322). Publisher full text and supporting PDF returned
   HTTP 403; no numeric dynamic-chi values were extracted from inaccessible
   full text. The abstract reports atmospheric measurements for spheres,
   cylinders, films, and fibers and identifies shape as a strong influence;
   this supports the importance of shape, not a verified numerical chi table.

5. **Triantafyllaki, M.; Chalvatzaki, E.; Torres-Agullo, A.; Karanasiou, A.;
   Lacorte, S.; Drossinos, Y.; Lazaridis, M. (2024). The fate of airborne
   microfibers in the human respiratory tract in different microenvironments.
   Science of the Total Environment 953, 176000.** DOI:
   <https://doi.org/10.1016/j.scitotenv.2024.176000>.
   Abstract verified through Europe PMC (PubMed 39233080). It uses dynamic
   shape factors for fibers of base diameters 1 and 10 micrometers and aspect
   ratios 3, 10, and 100. The full text was not available through the sources
   accessed, so no numerical chi was claimed from it.

6. **Dittmar, S.; Ruhl, A. S.; Altmann, K.; Jekel, M. (2024). Settling
   Velocities of Small Microplastic Fragments and Fibers.** DOI:
   <https://doi.org/10.1021/acs.est.3c09602>.
   Full text: <https://pmc.ncbi.nlm.nih.gov/articles/PMC11008250/>.
   The abstract explicitly reports experiments in **quiescent water** for
   fragments 9–289 micrometers and fiber lengths 50–600 micrometers. Do not
   transfer its aqueous settling velocities or shape descriptors directly
   into an air-settling dynamic-chi lookup.

## Meaning and use of chi in this revision

Dynamic chi compares drag on a particle with that on an equal-volume sphere
at the same relative speed in a specified regime. It depends on geometry and
orientation, and can depend on Reynolds/Knudsen regime. It is distinct from
sphericity, Corey shape factor, Aschenbrenner shape factor, and aspect ratio.
The AERMOD distance profiles use equivalent spherical surrogates, effectively
chi = 1, and do not become fiber/film simulations when a theoretical shape
factor curve is added elsewhere.

For the illustrative settling curves, retain
`v = (rho_p-rho_air) g d_v^2 Cc(d_v)/(18 mu chi)` using equal-volume diameter
and an explicitly constant selected chi. Dividing the sphere Cunningham
correction by a continuum/reference shape factor is an approximate sensitivity
calculation, especially at 0.5 micrometers and for slender shapes; a validated
morphology-specific slip/drag model is needed for quantitative nonspherical
predictions. Never imply that a single chi value resolves orientation,
folding, roughness, porosity, or aggregation.

No film or foam point is assigned in the delivered lookup. This preserves
the distinction between published reference geometry values and unsupported
claims about typical environmental morphotypes.
