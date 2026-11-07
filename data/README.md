# Recovered data

All 31 CSVs were retained, moved into these folders and verified against their
pre-move SHA256 hashes on 7 November 2026. No files were byte-identical.
`manifest.csv` records each filename, location, size, dimensions and hash.
`original_source_sha256.txt` records the unchanged original R source hashes.

## Inputs used by v0.7

`technology/` contains `input_ng`, `input_nwsg`, `input_cwsg`, `input_nwg`,
`input_nsg`, `input_wsg` and `input_swg`. Their first column names each
technology. The two recently recovered tables label it `type`; the other
five leave the column header blank. The new runner reads the first column
explicitly in both cases.

`traces/nem_trace2.csv` is the input named in the original main script.
It has 70,080 rows and 37 columns. Only `d.nem`, `w.mean` and `s.mean`
(columns 6–8) enter v0.7. Demand is interpreted as MW, converted to GW;
the resource columns are normalised output per unit of capacity.

- Weather labels run from 2003-07-01 00:00 to 2011-06-30 23:00.
- There are eight 8,760-hour financial-year blocks. February 29 is absent
  in 2004 and 2008. This explains the two 25-hour timestamp jumps.
- Demand is exactly repeated across all eight blocks, labelled 2049/2050.
  Thus one projected demand year is paired with eight weather years.
- Annual demand is 232.8075166 TWh, with mean 26.5762005 GW and peak
  42.8300775 GW. The five regional demand columns sum to NEM demand.
- Wind mean/range: 0.3863864 / 0.02–0.79. Solar: 0.3351874 / 0–0.97.
- No missing or nonfinite values occur in the three modelled columns;
  timestamps are unique and ordered. No timezone is documented.

The original script's “2003–2012” comment is inconsistent with these labels.
The model treats retained rows as consecutive one-hour model intervals; it
does not represent the removed leap days.

`traces/nem_trace.csv` has the same weather values and dates but different
demand. Its first demand year exactly matches
`archive/Scen2Demand_4950_10POE_delimited.csv`. Neither recovered demand-source
table exactly matches `nem_trace2.csv`, whose demand also differs from
`nem_trace.csv` by a nonconstant ratio. The transformation that produced
the selected demand trace remains unknown.

## Ancillary material

`archive/` contains:

- Two 8,760-row projected 2049–50 demand tables.
- Wind, solar and nuclear availability preparation traces, polygon samples,
  and preoptimised resource traces. v0.7 does not use the nuclear trace;
  it gives the first firm technology a constant dispatch profile.
- NSW demand/PV projections in daily rows with 48 period columns.
- Renewable supply and net-load experiments for 2016, 2020, 2026 and 2035.
- `may_trace.csv`, a 744-row sample with no calendar dates.
- `nuclear pv wind 8 July.csv`, a small scenario/results table.

Two differences matter if these files are reused:

- `wind.sup.trace.8yr.lp_yr.cut.csv` actually has 78,865 rows and date labels
  extending to 2012-07-01, despite the filename. Other resource files also
  differ in leap-day retention. Join them by verified timestamps rather
  than row number.
- `net_load_2026.csv` has 17,520 rows labelled 2026/27 followed by 48 rows
  labelled 2021. There are missing values in that trailing block, and 27
  missing `largepv` values overall. This file is not used by v0.7.

Origins, licences, monetary base year, preprocessing scripts and the
construction of `nem_trace2.csv` have not been recovered. Filenames alone
do not establish those facts.
