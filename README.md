# NEM energy modelling

A transparent chronological capacity-planning model for the Australian
National Electricity Market. This is an actively developed research baseline,
rebuilt from Barry W. Brook's small 2017 R model. It is not a contemporary
Australian energy-system assessment.

The model jointly chooses nameplate generation capacity and hourly dispatch
to minimise annual system cost. It supports nuclear, CCGT, open-cycle gas,
wind and solar; optional storage with independently sized power and energy;
carbon prices; and emissions-intensity limits averaged across weather years
or imposed in each year. Costs, energy and emissions are independently
reconstructed after every solve.

## Run the public example

Install [uv](https://docs.astral.sh/uv/), then:

```sh
uv sync --locked
uv run pytest -q
uv run energymod solve --config config/demo.toml --output outputs/demo
uv run energymod solve --config config/illustrative_storage.toml --output outputs/storage
```

The examples use a small synthetic trace included in the repository. All
generated results go into a new output directory; an existing directory is
never overwritten. Each successful run writes `summary.json`, `provenance.json`,
`capacity.csv`, `periods.csv` and compressed hourly `dispatch.csv.gz`.
Nonoptimal or independently invalid solutions fail explicitly.

`config/illustrative_storage.toml` demonstrates solar plus storage under a
zero-emissions constraint. Its storage assumptions are illustrative inputs,
not recovered historical estimates. Storage is disabled in the historical
baseline because the recovered files contain no battery parameters.

## Historical data

The recovered collection contains 31 CSVs, organised in `data/technology/`,
`data/traces/` and `data/archive/`. Every original file has a recorded SHA256
hash; no CSVs were discarded. The selected trace contains one repeated
projected 2049–50 demand year paired with eight weather years, July 2003–June
2011, with leap days removed.

The seven small technology tables and a derived engineering/economic
parameter table are included. Large traces and ancillary data remain outside
Git: their preparation history and redistribution terms are unresolved. The
[catalogue](docs/data_catalogue.md) and [manifest](data/manifest.csv) identify
them. A fresh clone can run the examples and tests without these files; tests
that require recovered raw data skip explicitly.

With the selected trace restored at the catalogued path:

```sh
uv run energymod check-inputs --config config/historical.toml
uv run energymod solve --config config/historical.toml --output outputs/historical
uv run energymod solve --config config/historical_low_emissions_one_year.toml --output outputs/limited
```

Technology assumptions use nameplate MW, annual fixed cost per MW, variable
cost per generated MWh and tCO2/MWh. The historical cost conversion is
reproducible with `uv run python scripts/convert_legacy_technologies.py`.
Monetary base year is unknown; these values are retained to develop the
modelling machinery, not as present-day prices.

`historical_low_emissions.toml` applies the limit across all eight weather
years and is a larger solver stress case. Time limits are explicit; a timed
out solve writes failure metadata and is never reported as an optimum.

## What the baseline means

Capacities are shared across the supplied weather years. Every supplied
hour must balance, while operating costs are averaged using explicit weights
that total 8,760 annual hours. Storage closes independently within each
weather year. Constant availability derates output; it does not represent
forced outages or establish power-system reliability.

This is a single-bus, greenfield model with continuous capacity and perfect
foresight. It omits transmission, regional build choices, reserves, unit
commitment, ramping and investment transitions. Thermal generation, including
nuclear, is fully flexible within its output bound. One returned optimum
does not establish a unique capacity mix.

## Replay on newer NEM data

The 2003–04 and joint fleets covered all 26,304 hours of reported NEM
dispatch demand from July 2023 through June 2026. With the same hourly
demand shape scaled to the original model's mean, they fell short in 22 and
18 hours respectively. All occurred on winter evenings. The replay uses a
fixed group of wind and solar farms, with demand and renewable availability
matched by timestamp. [Results, measured-demand checks and reproduction](results/modern_weather_replay/README.md)

## Project map

- [Methods and equations](docs/methods.md)
- [Eight-by-eight historical weather test, fleet failures and cost of coverage](results/weather_test_2017/README.md)
- [Validation evidence and bounded stress tests](docs/validation.md)
- [Data catalogue and unresolved provenance](docs/data_catalogue.md)
- [Development status and next work](docs/development.md)
- [Agent guide](AGENTS.md)
- [Original 2017 code and reconstruction audit](archive/2017/README.md)
- `src/energymod/`: input schema, readers, sparse LP, independent audit, reporting and CLI.
- `tests/`: analytical solutions, invariances, adversarial accounting checks and end-to-end examples.
- `config/`: explicit scenarios and reconstructed technology parameters.

The numerical backend is [SciPy's HiGHS linear-programming interface](https://docs.scipy.org/doc/scipy/reference/optimize.linprog-highs.html).
Dependencies are locked in `uv.lock`. Code is MIT; original project text,
figures and data are CC BY-SA 4.0, subject to the third-party data exclusions
above. See `LICENSE` and `LICENSE-CONTENT`.

Original model and scientific direction: Barry W. Brook. Reconstruction,
implementation, executable checks, documentation and delegated independent
review: OpenAI Codex (GPT-6), November 2026. See [contributions](docs/contributions.md).
