# Australian energy model: 2017 reconstruction

The original v0.7 dispatch model runs with the recovered inputs. Its cost and
some energy calculations have demonstrable defects; use this reconstruction
to understand the old experiment, rather than as an energy-system assessment.

The original `energmod_main_0.7.r` and `energmod_fn_0.7.r` are unchanged.
`run_legacy.R` supplies a working entry point, reads the technology names from
the first CSV column, uses R's built-in PSOCK workers, and supplies the original
function's global `iter` variable. It preserves the original dispatch, search,
and reported cost calculations. Additional columns calculate costs independently
for the same reported capacities and energy quantities.

## Run

Run commands from this directory. Only base R and its bundled `parallel`
package are needed. One worker is the default.

```sh
# Full trace, original 0.1 GW capacity sweep, nuclear and gas.
Rscript --vanilla archive/2017/run_legacy.R data/technology/input_ng.csv \
  --output outputs/legacy_ng_full_trace.csv

# Full trace, coarser search for nuclear, wind, solar and gas.
Rscript --vanilla archive/2017/run_legacy.R data/technology/input_nwsg.csv \
  --step 1 --precision 100 --output outputs/legacy_nwsg_coarse_full_trace.csv

# Counterexamples plus one-week smoke runs of all seven portfolios.
Rscript --vanilla archive/2017/check_accounting.R
```

The runner accepts `--trace`, `--output`, `--step`, `--precision`, `--workers`
and `--carbon`, each followed by a value. Defaults are
`data/traces/nem_trace2.csv`, `outputs/legacy_results.csv`, 0.1 GW, 1000,
one worker and $0/tCO2. The historical overbuild option is disabled.
The input trace uses the recovered `d.nem`, `w.mean`, `s.mean` columns in
positions 6–8, and each row is treated as one model hour.

For four-technology cases, the full default search is substantially larger
than the demonstrated coarse run. The test suite exercises the original
1000-point wind–solar search on one week of data. No claim of a global
minimum-cost system follows from this restricted search.

`check_accounting.R` is an audit reproducer: its ten `FAIL` records are known
defects reproduced in the historical code. A successful exit means those
defects were reproduced and the seven portfolio smoke runs completed with
balanced energy. It does not mean the historical model passes accounting.

## Files

- [Accounting review](ACCOUNTING_REVIEW.md): equations, counterexamples,
  actual run results and unresolved interpretation of availability.
- [Data notes](../../data/README.md): input roles, chronology and provenance gaps.
- [Input manifest](../../data/manifest.csv): dimensions, original filenames,
  present locations and SHA256 hashes of all 31 recovered CSVs.
- `data/technology/`: the seven generator parameter tables.
- `data/traces/`: the two assembled NEM traces; v0.7 selects `nem_trace2.csv`.
- `data/archive/`: the other 22 recovered files, retained as preparation
  material and related experiments.
- `outputs/`: generated scenario tables and accounting counterexamples.

The reference cost columns distinguish two possible meanings of installed
capacity (`IC`): nameplate capacity, or dependable capacity with nameplate
capacity equal to `IC/avail`. Both retain fixed costs for built but idle plant.
They use the historical reported energy, so they do not repair renewable
dispatch or attribution defects.

Reconstruction and checks: Codex (GPT-6), 7 November 2026. Verification used
R 4.6.2. These are the recovered 2017 numerical assumptions; currency base
year and the preparation history of the demand projection are undocumented.
