# Development status

## Approved direction

Barry authorised a complete overhaul on 7 November 2026: organise and
catalogue the recovered CSVs, archive the original R code, build a modern,
efficient foundation and create a public GitHub repository. The recovered
mid-2010s material supported the initial development. The first modern replay
uses AEMO data from July 2023 to June 2026.

## This foundation

- Original R source preserved byte for byte under `archive/2017/`.
- All 31 CSVs retained, catalogued and verified against source hashes.
- Explicit technology and canonical chronological trace schemas.
- Joint continuous capacity expansion and hourly dispatch using a sparse LP.
- Correct annual fixed/variable/carbon accounting; availability consistently
  expressed against nameplate capacity.
- Optional emissions limits with explicit expected/per-period semantics.
- Optional independently sized storage with physical losses and per-period cycles.
- Independent post-solve physics/accounting checks and reproducible result bundles.
- Public synthetic examples, dependency lock, analytical tests and CI.

Acceptance requires the analytical and adversarial tests to pass, both public
examples to run from a clean checkout, the full recovered trace to solve and
pass independent residual checks, and a public repository that excludes large
raw files and private operational material. Full-data diagnostic evidence is
recorded in `docs/validation.md`. The baseline and smaller constrained case
passed; the full constrained ensemble hit both tested algorithms' explicit
600-second limits and remains a performance follow-up.

## Next scientific work

1. Establish a consequential question and comparisons before adding more
   components. Candidate contrasts include the value of firm low-carbon
   generation under different emissions limits and storage assumptions.
   Profile the large constrained ensemble before a substantial scenario sweep;
   the current full-data emissions stress case exceeds the tested time budget.
2. Resolve or replace the projected-demand preprocessing. Choose current,
   documented demand/resource and cost sources, with explicit licences and
   monetary base years.
3. The [eight-by-eight historical weather test](../results/weather_test_2017/README.md)
   compares common capacity with independently optimised single-year fleets.
   The [modern replay](../results/modern_weather_replay/README.md) tests two
   fixed fleets on three subsequent years of coincident demand and renewable
   availability. A longer record and alternative wind footprints would test
   how often the winter evening shortfalls recur.
4. Examine near-optimal capacity ranges, cost uncertainty and out-of-sample
   weather operation before interpreting a specific capacity mix.
5. Add operational realism or regional transmission only where the selected
   question requires it. Use PyPSA if the scope becomes a network model.

Storage costs in the synthetic example are illustrative. No battery-cost
claim, contemporary optimum, policy recommendation, DOI release or manuscript
has been produced by this foundation tranche.
