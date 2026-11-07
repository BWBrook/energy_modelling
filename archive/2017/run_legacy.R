library(parallel)

read_generators <- function(path) {
  gen <- read.csv(path, stringsAsFactors = FALSE)
  rownames(gen) <- gen[[1L]]
  gen <- gen[-1L]
  required <- c("cf", "avail", "lcoe", "vom", "fuel.cost", "therm.effic", "co2")
  stopifnot(all(required %in% names(gen)), nrow(gen) >= 2L,
            tail(rownames(gen), 1L) == "gas",
            all(rownames(gen) %in% c("nuclear", "ccgt", "wind", "solar", "gas")),
            all(is.finite(as.matrix(gen[required]))),
            all(gen$cf > 0 & gen$cf <= 1),
            all(gen$avail > 0 & gen$avail <= 1),
            all(gen$therm.effic > 0), all(as.matrix(gen[required]) >= 0))
  gen$fuel.cost <- gen$fuel.cost * 3.6 / gen$therm.effic + gen$vom
  gen$lcoe <- gen$lcoe - gen$fuel.cost
  stopifnot(all(gen$lcoe >= 0))
  gen
}

read_trace <- function(path) {
  raw <- read.csv(path)
  stopifnot(identical(names(raw)[6:8], c("d.nem", "w.mean", "s.mean")))
  data.frame(demand = raw$d.nem, wind = raw$w.mean,
             solar = raw$s.mean, demGW = raw$d.nem / 1000)
}

reference_accounting <- function(result, gen, trace, carbon = 0) {
  types <- rownames(gen)
  capacity <- as.matrix(result[paste(types, "IC")])
  energy <- as.matrix(result[paste(types, "Prop")]) * sum(trace$demGW) * 1000
  fixed_rate <- gen$lcoe * gen$cf * nrow(trace) * 1000
  variable_rate <- gen$fuel.cost + carbon * gen$co2
  variable_cost <- as.vector(energy %*% variable_rate)
  denominator <- sum(trace$demGW) * 1000
  result$energy_share_sum <- rowSums(energy) / denominator
  result$cost_reference_IC_nameplate <-
    (as.vector(capacity %*% fixed_rate) + variable_cost) / denominator
  result$cost_reference_IC_dependable <-
    (as.vector(capacity %*% (fixed_rate / gen$avail)) + variable_cost) / denominator
  result$emissions_reference <- as.vector(energy %*% gen$co2) / denominator
  result
}

run_legacy_model <- function(gen, trace, step = 0.1, precision = 1000L,
                             workers = 1L, carbon = 0,
                             optimise = nrow(gen) >= 4L) {
  stopifnot(nrow(trace) > 0L,
            all(is.finite(as.matrix(trace[c("demand", "wind", "solar", "demGW")]))),
            all(trace$demGW >= 0), sum(trace$demGW) > 0,
            all(trace$wind >= 0 & trace$wind <= 1),
            all(trace$solar >= 0 & trace$solar <= 1),
            length(step) == 1L, is.finite(step), step > 0,
            precision >= 3L, precision == as.integer(precision),
            workers >= 1L, workers == as.integer(workers),
            is.finite(carbon), carbon >= 0)
  first <- rownames(gen)[1L]
  if (!first %in% c("wind", "solar")) trace[[first]] <- 1
  if (optimise) stopifnot(setequal(rownames(gen), c(first, "wind", "solar", "gas")),
                          first %in% c("nuclear", "ccgt"))
  iterations <- floor(max(trace$demGW) / step)
  stopifnot(iterations >= 1L)
  vars <- data.frame(c.price = carbon, grn.incr = step, opt = precision,
                     hr = nrow(trace), dem = sum(trace$demGW),
                     max.nem = max(trace$demGW), min.nem = min(trace$demGW),
                     overbuild = FALSE, iter = iterations)
  legacy <- new.env(parent = globalenv())
  sys.source("archive/2017/energmod_fn_0.7.r", envir = legacy)
  legacy$iter <- iterations
  cl <- makePSOCKcluster(workers)
  on.exit(stopCluster(cl))
  clusterExport(cl, "fn_renopt", envir = legacy)
  result <- legacy$fn_energmod(vars, gen, optimise, trace, cl)
  reference_accounting(result, gen, trace, carbon)
}

if (sys.nframe() == 0L) {
  args <- commandArgs(trailingOnly = TRUE)
  if (!length(args)) stop(paste(
    "Usage: Rscript run_legacy.R INPUT.csv [--trace FILE] [--output FILE]",
    "[--step GW] [--precision N] [--workers N] [--carbon DOLLARS_PER_TONNE]"))
  options <- list(trace = "data/traces/nem_trace2.csv",
                  output = "outputs/legacy_results.csv", step = "0.1",
                  precision = "1000", workers = "1", carbon = "0")
  if (length(args) %% 2L != 1L) stop("Each option needs a value")
  if (length(args) > 1L) for (i in seq.int(2L, length(args), by = 2L)) {
    key <- sub("^--", "", args[i])
    if (!startsWith(args[i], "--") || !key %in% names(options)) stop("Unknown option: ", args[i])
    options[[key]] <- args[i + 1L]
  }
  gen <- read_generators(args[1L])
  trace <- read_trace(options$trace)
  started <- proc.time()
  result <- run_legacy_model(gen, trace, as.numeric(options$step),
                             as.numeric(options$precision), as.numeric(options$workers),
                             as.numeric(options$carbon))
  dir.create(dirname(options$output), recursive = TRUE, showWarnings = FALSE)
  write.csv(result, options$output, row.names = FALSE)
  cat(nrow(trace), "hourly rows;", nrow(result), "capacity combinations\n")
  cat("Energy share sum range:", range(result$energy_share_sum), "\n")
  cat("Lowest legacy cost in this sweep:", min(result$av.lcoe), "$/MWh\n")
  cat("Output:", options$output, "\n")
  print(proc.time() - started)
}
