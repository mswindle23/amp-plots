# Independent scientific validation

Passed: 30 native AERMOD jobs across 10 controlled cases. Each case contains 24 valid modeled hours and 2,736 terrain receptors.

The audit reads authentic native ASCII files directly, independently of the plotting and Excel export tables. It verifies current execution/input/output hashes; constant weather within each case; physically consistent friction velocity and tiny heat flux; common stability and other prescribed controls; exactly repeating hourly receptor fields; PERIOD mean concentration; and PERIOD summed deposition within scientific-format rounding.

No fatal errors occurred. The 15 no-rain quantity runs each produce one expected MX W496 warning because wet deposition remains enabled with zero precipitation; this is the intended control. All 15 rain runs have zero warnings. No other warning codes are accepted.

The merged terrain is the exact union of four successful native full-tile AERMAP runs. All 873 original receptors remain, with ground and hill heights agreeing within 0.01 m. The 1,863 additional receptors improve resolution along the eastward plume.

Every no-rain case has exactly zero wet deposition. At the same wind speed, introducing rain does not increase concentration or dry deposition because wet plume depletion is also active. All three output quantities use the same particle, source, terrain and meteorology per case.

Hourly deposition is an amount in µg/m² over one hour, numerically equal to mean flux in µg/m²/h. PERIOD deposition is accumulated µg/m² across 24 hours; concentration is a mean in µg/m³. Identical stationary forcing gives constant hourly flux and linearly increasing accumulation; this does not model plume startup or advancing-puff travel time.

The common year is a calendar/reference label. Available regional observations do not establish a complete annual Clemson microplastic inventory. Source emissions and synthetic weather remain explicit scenario assumptions. Friction velocity and heat flux change with reference wind across speeds; the experiment is not described as holding every turbulence quantity fixed while changing wind.

Detailed per-case numeric checks and exact native file hashes are in `independent_validation.json`.
