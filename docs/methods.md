# Baseline formulation

## Scope

The model finds an optimal greenfield single-bus NEM portfolio under supplied
technology and resource assumptions. Nameplate capacities are common across
empirical weather periods. Dispatch and storage operation use perfect
foresight within each period. Every sampled interval must be feasible;
operating costs are expected annual values across equally weighted periods.
This combines adequacy over all sampled hours with average operating cost.

The recovered data represent QLD, NSW, VIC, SA and TAS. They do not cover
Western Australia or the Northern Territory. One projected demand year is
repeated, while weather varies. Fixed spatial resource averages are scaled
with capacity; the model does not optimise locations.

The [modern fixed-fleet replay](../results/modern_weather_replay/README.md)
uses hourly AEMO data for the same five regions. It keeps the historical
capacity vectors and tests three demand definitions. Its methods describe the
fixed renewable sites, market clock, demand scaling and checks on source gaps.

## Generation and costs

For technology `i` and snapshot `t`, capacity `K_i` and dispatch `g_ti` are
nonnegative, with optional minimum and maximum capacity bounds:

```text
g_ti <= K_i * availability_i * profile_ti
sum_i(g_ti) + discharge_t - charge_t = demand_t
```

Firm generation has profile one. Availability is a deterministic derating,
not a stochastic outage process. For wind and solar, the reconstructed
baseline multiplies the resource trace by 0.99. Whether the original
profiles already included plant availability remains unknown; an availability
of one is therefore a useful recorded sensitivity before interpreting results.

With annual fixed costs `F_i`, variable costs `V_i`, carbon price `p`,
emissions intensity `e_i` and annual operating weights `w_t`, the objective is:

```text
sum_i(F_i * K_i) + sum_ti(w_t * g_ti * (V_i + p * e_i))
  + storage_annual_fixed_cost + storage_weighted_discharge_cost
```

Fixed costs are paid even for idle capacity. No output-dependent cost is
multiplied by capacity factor. Generation costs are summed before division
by demand MWh. Carbon payments are reported separately from resource costs;
the objective includes those payments when a carbon price is specified.

The historical parameter converter uses:

```text
V = fuel_price_per_GJ * 3.6 / thermal_efficiency + variable_OM
F = (reference_LCOE - V) * reference_capacity_factor * 8760
```

This treats reference LCOE net of variable cost as a capacity-proportional
annual cost. It reconstructs the old numerical assumptions; the modern model
accepts `F` and `V` directly. Monetary base year and the original costing
method are unknown. Unlimited expandable assets require positive fixed
cost; a zero-cost asset requires a finite capacity bound.

## Period weights and emissions

Annual weights sum to 8,760 hours. Each empirical period receives equal
probability; within a period, weights are proportional to interval duration.
The recovered eight 8,760-hour periods therefore have `w_t = 1/8` for each
retained hour. Capital costs enter once, not eight times. All demand, energy,
variable-cost and emissions statistics use the same weights.

The optional emissions-intensity constraint is:

```text
sum_ti(w_t * g_ti * e_i) <= limit * sum_t(w_t * demand_t)
```

`emissions_limit_scope = "expected"` applies this across all snapshots.
`"per_period"` applies a separate constraint within every weather period.
The expected cap can permit one weather year to exceed the average limit.
The per-period historical example uses 0.1 tCO2/MWh as an illustrative
diagnostic constraint, not a calibrated policy target.

## Storage

Storage has independent power capacity `P` in MW and energy capacity `E`
in MWh. Charge and discharge are each bounded by `P`; end-of-interval state
of charge is bounded by `E`. For physical duration `d_t`:

```text
soc_t - soc_previous = eta_charge * charge_t * d_t
                        - discharge_t * d_t / eta_discharge
```

The predecessor of the first snapshot is the last snapshot of the same
weather period. Every period is independently cyclic. This prevents free
initial/terminal energy and transfer between alternative weather years.
Annual probability weights never advance the state of charge. The omitted
February 29 dates in historical inputs do not create 25-hour model intervals.

The continuous LP does not enforce binary charge/discharge exclusivity.
Overlap is measured and reported as a warning above tolerance; the
illustrative example includes an explicit small discharge-throughput cost.
No battery assumptions are inferred from the old generator cost tables.

## Solver and independent checks

The sparse LP is passed to
[SciPy's HiGHS interface](https://docs.scipy.org/doc/scipy/reference/optimize.linprog-highs.html).
Only an optimal solve proceeds to reporting. A separate audit, without
solver constraint matrices, reconstructs hourly balances, generation and
capacity bounds, storage equations and closures, costs and emissions caps.
Default audit tolerances are `1e-5` absolute plus `1e-8` relative to the
quantity being checked. Residuals and cost reconciliation are saved.

`solver_method` selects `highs` (automatic), `highs-ipm` (interior point)
or `highs-ds` (dual simplex). The large emissions-constrained example selects
interior point explicitly; the configuration and solver message record the
choice. All methods solve the same continuous LP.

The formulation follows the separation of fixed investment and weighted
operating costs also used by [PyPSA](https://docs.pypsa.org/latest/user-guide/optimization/objective/).
For this single-bus reference implementation, a sparse LP keeps the equations
small and directly inspectable. Regional networks, transmission expansion
or sector coupling would justify moving to PyPSA rather than duplicating
its component framework here.

Every run records input and source hashes, configuration, package versions,
Git state, solver status, timing and independent residuals. Reports expose
each weather period separately. One optimal solution may be nonunique.

## Limits on interpretation

This model has no existing fleet, build schedule, unit commitment, minimum
stable generation, ramping, start costs, reserves, forced outages, networks
or security constraints. Nuclear can dispatch between zero and its constant
derated output bound. Demand and future resource portfolios are supplied,
not forecast. Historical calibration, cost uncertainty and unknown demand
preprocessing dominate any contemporary interpretation. A successful solve
establishes conditional feasibility and cost within this LP, not reliability
or an actionable build plan.
