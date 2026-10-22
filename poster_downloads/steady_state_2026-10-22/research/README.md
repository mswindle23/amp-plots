# Data-year and source selection for the controlled plume scenarios

The common **reference year is 2024**. This is the latest geographically nearby
atmospheric microplastic measurement year verified in this targeted search, not
a claim that a complete annual Clemson microplastics inventory exists. The
model's July 15, 2024 timestamps label a controlled experiment. The fixed wind,
stability, temperature, humidity, and rainfall fields are synthetic and do not
reconstruct observed weather on that date.

## Recent regional measurements

**Gray et al. (2026), Influence of Hurricane Helene on microplastic deposition in
the mountainous southeastern United States**, DOI
[10.1093/inteam/vjag130](https://doi.org/10.1093/inteam/vjag130), published August 5,
2026, reports **2024** measurements at Iron Duff, Coweeta Hydrologic Laboratory,
and Highlands Biological Station, North Carolina. The verified abstract
describes pre-hurricane sampling in January–September, the September event,
and post-event sampling in October–November. It reports storm-integrated
deposition of **1,280, 2,179, and 10,243 particles/m²**, respectively, representing
4.2%, 4.6%, and 18.8% of annual deposition as characterized by the authors.

These observations are supplied in `regional_observations_2024.csv`. They are
**event-integrated particle counts**, not g/m²/h fluxes or source emissions.
Crossref metadata and the Europe PMC abstract were inspected. Full-calendar
coverage and the underlying particle-by-particle data were not verified from
those sources. No claim of complete 365/366-day local data is made. A targeted
search of publications through October 22, 2026, did not verify a newer nearby
atmospheric sampling year; that limited search cannot establish global absence
of other datasets.

An earlier, fully inspected regional study provides additional context:
**Elnahas et al. (2024), Atmospheric Deposition of Microplastics in South Central
Appalachia in the United States**, DOI
[10.1021/acsestair.4c00189](https://doi.org/10.1021/acsestair.4c00189),
[full text](https://pmc.ncbi.nlm.nih.gov/articles/PMC11730859/). Two rural Virginia
sites were sampled during five 21-day periods between March and September
2023. Table 1's ten deposition-rate observations are transcribed in
`regional_observations_2023.csv`, retaining their reported uncertainties.
The published regional mean is 68 particles/m²/day. Of 35 spectroscopically
confirmed particles, 51% were fibers, 40% fragments, and 9% films; PETE was
the most frequent identified polymer. This is neither a full-year Clemson
dataset nor a mass-emissions inventory.

**Neither regional dataset calibrates the modeled emission rate.** Particle
count deposition cannot be converted into an emission mass rate without a
size/shape/mass distribution, source attribution, and a suitable inverse model.
The wet and dry components were not separately measured in the supplied
regional context values. These context data must remain separate from native
AERMOD scenario inputs and outputs in the workbook.

## Literature-supported illustrative emissions magnitude

The hypothetical source represents a 100 m × 100 m roadside/road-dust patch
containing a tire-wear microplastic aerosol surrogate. No real facility or
measured road inventory is identified. The constant emission is derived from:

| Quantity | Value | Evidence/status |
|---|---:|---|
| Traffic activity | 10,000 vehicles/day | Assumed scenario activity, not an SCDOT count |
| Effective contributing road length | 0.1 km | Assumed segment |
| Total tire wear | 0.1 g/(vehicle km) | Cited estimate in Kole et al. 2017 review |
| Airborne PM10 share of wear | 10% | Central modeling assumption in Evangeliou et al. 2020 |
| Airborne surrogate mass | 10 g/day | Product of the four factors above |
| Constant source rate | 0.00011574074074074075 g/s | 10 g/day ÷ 86,400 s/day |

Kole et al., **Wear and Tear of Tyres: A Stealthy Source of Microplastics in the
Environment**, DOI [10.3390/ijerph14101265](https://doi.org/10.3390/ijerph14101265),
[full text](https://pmc.ncbi.nlm.nih.gov/articles/PMC5664766/), reports the
0.1 g/(vehicle km) total-wear estimate while reviewing the Luhana et al.
emissions approach. Total wear includes material that does not become airborne.

Evangeliou et al., **Atmospheric transport is a major pathway of microplastics
to remote regions**, DOI
[10.1038/s41467-020-17201-9](https://doi.org/10.1038/s41467-020-17201-9),
[full text](https://pmc.ncbi.nlm.nih.gov/articles/PMC7360784/), uses a central
airborne PM10 share of about 10%, with sensitivity cases of 2.5%, 5%, 10%,
20%, and 40%. That study assumes a tire-wear particle density of **1,234 kg/m³**.
Those values establish a plausible screening magnitude and material-density
reference; they do not validate emissions from the selected Clemson location.

The controlled runs use **5 µm equivalent spherical surrogates**, density
1,234 kg/m³, and χ = 1. This monodisperse representation is a selected modeling
case, not the measured regional size distribution. Tire wear is a composite
material; the emission above is not a measured pure-polymer mass. Real roads
contain additional resuspended material, and emission rates can depend on rain,
traffic, and wind. Holding the source constant isolates the requested model
sensitivity rather than predicting those emission feedbacks.

## Verification and retained evidence

`source_and_year_selection.json` provides the machine-readable assumptions and
references. `research_retrieval.json` records source URLs and SHA256 hashes of
retrieved metadata and article XML. Large/raw retrievals are retained only in
the ignored `cache/` directory; curated numeric tables and this review are the
portable evidence. Regional count-based observations are context, not model
validation against the synthetic-weather, mass-based plume simulations.
