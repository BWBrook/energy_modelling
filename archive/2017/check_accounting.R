source("archive/2017/run_legacy.R")
legacy <- new.env(parent = globalenv())
sys.source("archive/2017/energmod_fn_0.7.r", envir = legacy)
dir.create("outputs", showWarnings = FALSE)

checks <- list()
record <- function(id, expected, observed, units, note) {
  checks[[length(checks) + 1L]] <<- data.frame(
    check = id, expected = expected, legacy = observed,
    difference = observed - expected, units = units,
    status = if (is.finite(observed) && abs(observed - expected) < 1e-7) "PASS" else "FAIL",
    note = note)
}
trace <- function(demand, wind = rep(0, length(demand)), solar = rep(0, length(demand))) {
  data.frame(demand = demand * 1000, wind = wind, solar = solar, demGW = demand)
}
error_text <- function(expr) tryCatch({ force(expr); "" }, error = conditionMessage)

equal <- legacy$fn_renopt(1, c(1, 1), 10,
                         data.frame(wind = c(1, 0.5), solar = c(1, 0.5)))
record("renewable_exact_match_energy", 2,
       equal$win.use + equal$sol.use + sum(equal$ren.gap), "GWh",
       "Exact-match hours are omitted from useful renewable energy")
for (case in c("all_equal", "zero_resources")) {
  resource <- if (case == "all_equal") 1 else 0
  err <- error_text(legacy$fn_renopt(1, c(1, 1), 10,
                                    data.frame(wind = rep(resource, 2), solar = rep(resource, 2))))
  record(paste0("renewable_", case, "_returns_result"), 1, as.numeric(!nzchar(err)),
         "boolean", err)
}

attribution <- legacy$fn_renopt(1, c(1, 0), 10,
                               data.frame(wind = c(0, 1), solar = c(1, 0)))
record("wind_energy_when_wind_only_at_zero_residual", 0, attribution$win.use,
       "GWh", "Annual pre-curtailment allocation assigns unusable wind to demand")

ng <- read_generators("data/technology/input_ng.csv")
nwsg <- read_generators("data/technology/input_nwsg.csv")
cwsg <- read_generators("data/technology/input_cwsg.csv")
tiny <- trace(c(0.5, 1, 0.5, 1), c(0.2, 0.8, 0.6, 0.4), c(0, 0.5, 0.7, 0))
ng0 <- run_legacy_model(ng, tiny, step = 0.5, precision = 10)
ng100 <- run_legacy_model(ng, tiny, step = 0.5, precision = 10, carbon = 100)
gas <- ng["gas", ]
gas_reference <- gas$lcoe * gas$cf / ng0$`gas CF`[1L] + gas$fuel.cost
record("gas_cost_at_half_physical_capacity_factor", gas_reference, ng0$`gas LCOE`[1L],
       "$/MWh generated", "Reference preserves the legacy dependable-capacity convention")
record("carbon_charge_matches_emissions", 100 * ng0$CO2.MWh[1L],
       ng100$av.lcoe[1L] - ng0$av.lcoe[1L], "$/MWh demand",
       "Same dispatch; carbon price increases from zero to 100 dollars per tonne")
stopifnot(abs((ng100$cost_reference_IC_dependable[1L] -
               ng0$cost_reference_IC_dependable[1L]) -
              100 * ng0$emissions_reference[1L]) < 1e-8)

four <- run_legacy_model(nwsg, tiny, step = 0.5, precision = 10)
for (type in c("wind", "solar")) {
  ref <- nwsg[type, "lcoe"] * nwsg[type, "cf"] / four[[paste(type, "CF")]][1L] +
    nwsg[type, "fuel.cost"]
  record(paste0(type, "_variable_operating_cost"), ref, four[[paste(type, "LCOE")]][1L],
         "$/MWh generated", "Optimised branch omits the variable operating cost")
}

idle <- run_legacy_model(nwsg, trace(c(1, 1)), step = 0.5, precision = 10, optimise = FALSE)
idle_capacity <- c(idle$`wind IC`[1L], idle$`solar IC`[1L])
idle_fixed <- sum(idle_capacity * nwsg[c("wind", "solar"), "lcoe"] *
                   nwsg[c("wind", "solar"), "cf"] / nwsg[c("wind", "solar"), "avail"])
idle_observed <- sum(c(idle$`wind Prop`[1L], idle$`solar Prop`[1L]) *
                       c(idle$`wind LCOE`[1L], idle$`solar LCOE`[1L]), na.rm = TRUE)
record("fixed_cost_of_built_but_idle_renewables", idle_fixed, idle_observed, "$/MWh demand",
       "Positive installed capacities have zero output; NaN weighted costs are discarded")
stopifnot(all(idle_capacity > 0), idle$`wind Prop`[1L] == 0,
          idle$`solar Prop`[1L] == 0, is.infinite(idle$`wind LCOE`[1L]))

ccgt <- run_legacy_model(cwsg, tiny, step = 0.5, precision = 10)
record("ccgt_and_gas_emissions", ccgt$emissions_reference[1L], ccgt$CO2.MWh[1L],
       "tCO2/MWh demand", "CCGT emissions use gas energy share instead of CCGT share")

results <- do.call(rbind, checks)
write.csv(results, "outputs/accounting_counterexamples.csv", row.names = FALSE)
stopifnot(nrow(results) == 10L, all(results$status == "FAIL"))

constant <- data.frame("nuclear IC" = 1, "gas IC" = 0,
                       "nuclear Prop" = 1, "gas Prop" = 0, check.names = FALSE)
constant1 <- reference_accounting(constant, ng, trace(rep(1, 24)))
constant2 <- reference_accounting(constant, ng, trace(rep(1, 48)))
stopifnot(abs(constant1$cost_reference_IC_dependable - 89.3) < 1e-8,
          abs(constant1$cost_reference_IC_nameplate - 83.3007058823529) < 1e-8,
          identical(constant1, constant2))

raw <- read_trace("data/traces/nem_trace2.csv")
for (path in list.files("data/technology", "^input_.*[.]csv$", full.names = TRUE)) {
  gen <- read_generators(path)
  result <- run_legacy_model(gen, raw[1:168, ], step = 2, precision = 1000)
  stopifnot(all(is.finite(result$av.lcoe)),
            all(abs(result$energy_share_sum - 1) < 1e-8),
            all(is.finite(result$cost_reference_IC_dependable)))
  output <- paste0("outputs/smoke_", sub("[.]csv$", "", basename(path)), ".csv")
  write.csv(result, output, row.names = FALSE)
}
cat(nrow(results), "known accounting failures reproduced; seven portfolio smoke runs passed.\n")
print(results[c("check", "expected", "legacy", "units")], row.names = FALSE)
