# Data catalogue

The recovered directory contains 31 CSV files. The raw files remain in
`data/technology`, `data/traces` and `data/archive`; no raw file is rewritten
by the catalogue process. `data/manifest.csv` records their pre-catalogue
paths, dimensions and SHA256 digests. Run `python scripts/catalogue_data.py`
to verify every digest and regenerate `data/catalogue.csv`.

`data/traces/nem_trace2.csv` is the selected legacy trace. It contains 70,080
rows: eight 8,760-hour July–June weather years from 2003–04 through 2010–11.
The projected demand series is repeated over those weather years, while wind
and solar vary. Leap days are removed to retain standard 8,760-hour model
blocks. The provenance and transformation of the projected demand are not
known. The loaders preserve chronological gaps and give storage the explicit
one-hour model duration rather than treating the two 25-hour calendar gaps as
storage intervals.

The 2017 source files have no recovered licence, currency base year, or
preprocessing script. The derived `config/technologies_2017.csv` is a strict,
documented translation of those values: fixed cost is `(LCOE - fuel - VOM) ×
reference capacity factor × 8760`, variable cost is fuel plus VOM per MWh,
and wind/solar availability is the supplied 0.99 weather-only derating.

The remaining files are retained as preparation material. They have differing
calendar conventions and should be joined on timestamps, never by row number.
`net_load_2026.csv` contains a trailing 48-row block labelled 2021 with missing
values. It is not used by the modern baseline.
