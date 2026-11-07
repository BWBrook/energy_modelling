# Working in this repository

Read `README.md`, `docs/methods.md`, `docs/development.md` and the relevant
tests before changing the model. This is an early NEM research baseline;
historical examples do not establish a present-day energy-policy result.

Use `uv sync --locked` and `uv run pytest -q`. The public synthetic cases
must run in a fresh clone without recovered raw data. Raw-data tests may
skip only when the named input file is absent. Run a relevant end-to-end
configuration after changing the solver, data readers or accounting.

The important contracts are:

- Nameplate capacity and dispatch are MW, stored energy is MWh.
- Annual fixed costs enter once; annual operating weights sum to 8,760 hours.
- Physical durations advance storage; annual probability weights never do.
- Capacity is common across empirical weather periods; storage closes within
  each period, including in selected subsets.
- Fixed costs remain payable when capacity produces no energy.
- Post-solve accounting is independent of the LP matrices and must pass.
- Availability is explicit deterministic derating. Changes to its meaning,
  curtailment, scenario weighting or emissions-policy scope must be documented
  and tested as scientific changes.

`archive/2017/energmod_main_0.7.r` and `energmod_fn_0.7.r` preserve the original
bytes. Their hashes are in `data/original_source_sha256.txt`. Leave the old
implementation archived; new work belongs in `src/energymod/`.

Catalogue recovered inputs with `uv run python scripts/catalogue_data.py`.
Regenerate the engineering parameter table with
`uv run python scripts/convert_legacy_technologies.py`. Verify source hashes
and record provenance when replacing data. Keep large raw files, generated
dispatch and local operational details out of Git. Do not silently reuse
files with different calendars by matching row number.

The next data source should enter through the canonical trace and technology
schemas. Add modelling complexity only for an explicit scientific question.
Prefer PyPSA over extending this small solver into a general network platform
if regional transmission or sector coupling becomes the objective.
