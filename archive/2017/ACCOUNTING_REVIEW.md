# Accounting check, 7 November 2026

The historical functions run against the recovered data through
`run_legacy.R`. The original R files remain unchanged. Runtime adaptations
are technology labels, a built-in PSOCK cluster instead of the old `SOCK`
backend, and an explicit environment supplying the original global `iter`.
The independent review and executable counterexamples agree on the defects
below. This is a reconstruction and accounting audit, not a new scientific
comparison of energy-system options.

## Demonstrated runs

| Portfolio | Trace | Capacity step | Wind–solar precision | Combinations |
|---|---|---:|---:|---:|
| Nuclear, gas | All 70,080 rows | 0.1 GW | Not used | 428 |
| Nuclear, wind, solar, gas | All 70,080 rows | 1 GW | 100 | 42 |
| All seven supplied portfolios | First 168 rows | 2 GW | 1000 where applicable | 20 each |

The sum of generation energy shares differs from one by at most about
`8.6e-11` in the full-trace runs, consistent with rounding. All seven
one-week smoke runs completed with finite total costs and balanced energy.
The complete default four-technology search (0.1 GW, precision 1000) was
not run. These checks demonstrate execution and aggregate accounting for
these cases; the counterexamples below show why that is not general validity.

## Consistent reference cost

The recovered input tables contain a reference LCOE `L`, reference capacity
factor `c`, fuel price in $/GJ, thermal efficiency `eta`, variable O&M and
emissions intensity. Following the original conversion:

```text
v = fuel_price * 3.6 / eta + variable_OM        [$ / MWh generated]
f = L - v                                    [$ / MWh at reference CF]
cost_over_H_hours = f * c * K_nameplate * H + (v + carbon_price * co2) * E
```

`K_nameplate` is MW, `H` is the number of model hours and `E` is delivered
MWh. Sum technology costs first, then divide by total demand MWh. This
retains fixed costs for built generators with no output. It assumes the
input LCOE is evaluated at its supplied reference capacity factor and that
`L-v` represents costs proportional to capacity.

For positive output the corresponding unit generation cost is
`f*c/CF_actual + v + carbon_price*co2`. Variable cost per generated MWh does
not receive another capacity-factor multiplier.

Availability has two possible interpretations. The old code dispatches `IC`
but multiplies the resulting capacity factor by `avail`. This can be
reconciled if `IC` is dependable capacity and nameplate capacity is `IC/avail`.
If `IC` means nameplate capacity, its reported CF is inconsistent with the
dispatched energy and availability is absent from dispatch. The sources do
not settle the intended interpretation. Reference columns report both
possibilities; neither changes the original dispatch. A future repair needs
an explicit interpretation of capacity and whether the resource traces
already incorporate availability.

## Reproduced defects

`Rscript --vanilla archive/2017/check_accounting.R` writes
`outputs/accounting_counterexamples.csv`. Its ten failed checks are
deliberately small counterexamples, not ten independent defect classes.

1. **Variable costs and carbon charges are incorrectly scaled by CF.**
   Function lines 50, 67 and 95 multiply already converted $/MWh costs by
   realised CF divided by reference CF. For the supplied gas assumptions,
   variable cost is $75.828571/MWh and the reference fixed component is
   $53.571429/MWh. At physical utilisation of 0.5, the old reported CF is
   0.475 after its availability multiplier. It reports **$202.649248/MWh**,
   against **$98.384962/MWh** under the dependable-capacity interpretation
   or **$97.257143/MWh** if `IC` is nameplate. In a fixed-dispatch test,
   a $100/t carbon price adds $49.083333/MWh of demand instead of the
   $20.666667/MWh implied by the model's own emissions.

2. **Optimised wind and solar omit variable O&M.**
   Main lines 18–19 subtract variable O&M from input LCOE. Function lines
   79 and 84 restore only the fixed part, dropping the supplied $5/MWh
   for wind and $2/MWh for solar.

3. **Built but idle plant loses its fixed costs.**
   Zero output produces infinite LCOE, then `0*Inf = NaN`; function line
   99 discards it with `na.rm=TRUE`. The counterexample installs 0.5 GW
   each of wind and solar with zero resource output. Their fixed costs
   should add $28.860101/MWh of demand under the dependable convention;
   the old total includes none of that cost. A zero-capacity generator
   also has undefined CF/LCOE, but its zero fixed cost is legitimate.

4. **Exactly matched renewable hours lose energy.**
   Function lines 6–11 classify residual minus output as strictly positive
   or negative, omitting equality from useful renewable energy. With
   demand `(1,1)` GW and both resource traces `(1,0.5)`, 1 GW renewable
   capacity gives 1.5 GWh useful renewable output and 0.5 GWh gas. The
   old function accounts for only 0.5 GWh renewable output plus 0.5 GWh
   gas: half the 2 GWh demand disappears. All-equality or all-zero-resource
   cases instead crash because `w.prop` and `ren.max` are uninitialised.

5. **Wind and solar attribution ignores when curtailment occurs.**
   Function lines 15–16 allocate useful energy according to annual gross
   resource proportions. If wind occurs only when residual demand is
   zero, it can still receive a positive served-energy share. The tiny
   test assigns 0.16 GWh useful wind when physically none is possible.
   Combined renewable energy can balance while individual shares and CFs
   are wrong. A repair must specify within-hour curtailment allocation.

6. **CCGT emissions use the gas energy share.**
   Function line 101 uses `rt` after it has been overwritten with gas
   results. In the `input_cwsg.csv` counterexample, reported emissions are
   0.145 tCO2/MWh instead of 0.3432333 tCO2/MWh from the same generation
   shares. This affects a recovered scenario, not just hypothetical inputs.

## Effect on the historical results

In the full nuclear–gas sweep, the old minimum is $97.12503/MWh at
25.53008 GW nuclear and 17.3 GW gas. The consistent cost for exactly that
dispatch is $100.1163/MWh under the dependable-capacity interpretation.

The strongest discrepancy is at the other end of that sweep: 0.0300775 GW
nuclear and 42.8 GW gas. The old calculation gives **$241.4117/MWh**;
the reference gives **$94.00694/MWh**. That latter row becomes the lowest
reference-cost row in the sampled nuclear–gas sweep. Therefore the cost
bug changes portfolio ranking, rather than merely shifting all prices.
These are diagnostic results using the supplied historical assumptions,
zero carbon price and the original unrestricted gas backup. They are not
recommendations for the contemporary Australian system.

In the coarse four-technology sweep, the old lowest-cost row is
$93.22780/MWh, but its reference cost is $96.88330/MWh. The lowest reference
row differs. Those reference columns still use the original technology
energy attribution; they are not a fully corrected renewable model.

## Scope of a subsequent repair

Keep the recovered sources as the historical baseline. A corrected version
should calculate total fixed and variable costs directly, retain idle plant
costs, use per-hour renewable energy and curtailment accounting, handle empty
and exact-match cases, and sum emissions across all technologies. State the
capacity/availability convention before interpreting the results.

The search also excludes a pure first-technology portfolio and pure
wind/solar endpoints, and its wind–solar objective maximises useful energy
rather than minimising system cost. Storage, transmission, outages and other
operational constraints are absent. Those are modelling choices to revisit
when a new scientific question is selected, rather than runtime repairs.

Authorship: reconstruction, executable checks and independent code audit by
Codex (GPT-6), including one delegated read-only reviewer. Original model:
Barry W. Brook, 2017.
