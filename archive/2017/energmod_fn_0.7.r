
fn_renopt <- function(incr, gap, prec, fn.tr) { ## Optimize wind-solar mix for renewable penetration level
  ren.use <- 0
  for(j in 2: (prec-1)) { # Have at least some fraction of wind and solar, to avoid NaN errors
    ren.tot <- incr*(j/prec)*fn.tr$wind + incr*(1-j/prec)*fn.tr$solar
    ren.full <- which(gap-ren.tot<0) # hours where  renewables meet all of the demand gap left by nuclear
    ren.part <- which(gap-ren.tot>0) # hours where only  part of the demand gap left by nuclear is filled

    if((sum(gap[ren.full])+sum(ren.tot[ren.part]))>ren.use) {
      w.prop <- j/prec
      ren.use <- sum(gap[ren.full])+sum(ren.tot[ren.part])
      ren.max <- ren.tot
    }
  }
  win.use <- ren.use*((w.prop*sum(fn.tr$wind))/((w.prop*sum(fn.tr$wind))+((1-w.prop)*sum(fn.tr$solar))))
  sol.use <- ren.use-win.use
  ren.gap <- pmax(0,gap-ren.max)
  return(list(w.prop=w.prop, win.use=win.use, sol.use=sol.use, ren.gap=ren.gap))
}

fn_energmod <- function(fn.var, fn.gen, fn.sel, fn.tr, cl){ # Main model run - uses parSapply for parallel computing

  rn <- expand.grid(row.names(fn.gen), c('IC','CF','Prop','LCOE'))
  rn <- paste(rn[,1], rn[,2])
  rt.temp <- data.frame(array(NA, c(nrow(fn.gen),4)))
  names(rt.temp) <- c('IC','CF','Prop','LCOE')
  rownames(rt.temp) <- row.names(fn.gen)
  
  clusterExport(cl, varlist = c('rn','rt.temp','fn.var','fn.gen','fn.sel','fn.tr'), env=environment()) 
  
  rt <- parSapply(cl, 1: iter, function(i) {
    rtt <- rt.temp
    grn <- i * fn.var$grn.incr
    if(fn.var$overbuild == T) max.nem <- fn.var$max.nem * fn.var$overbuild else max.nem <- fn.var$max.nem
    
    if(fn.sel == F) for(j in 1: (nrow(fn.gen)-1)){
      nm <- rownames(fn.gen)[j]; sg <- fn.gen[nm,]; rt <- rtt[nm,]; tr <- fn.tr[,nm]
      
      if(j == 1){
        dem <- fn.tr$demGW          # demand trace
        rt$IC <- max.nem - grn      # required capacity
      } else{
        dem <- gap
        if(j == 2) rt$IC <- grn else rt$IC <- max(dem)
      }
      
      use <- round(sum(pmin(dem, rt$IC * tr)),digits=10) # actual demand consumed
      rt$Prop <- round(use / fn.var$dem, digits=10) # proportion = total consumption / demand
      rt$CF <- round((use * sg$avail) / (rt$IC * fn.var$hr), digits=10) # market capacity factor gen.max
      rt$LCOE <- round((sg$lcoe*(sg$cf/rt$CF)) + ((sg$fuel.cost+(fn.var$c.price*sg$co2))*rt$CF/sg$cf), digits=10)
      gap <- pmax(0, dem - rt$IC * tr)
      rtt[nm,] <- rt
        
    } else{

      nm <- rownames(fn.gen)[1]
      sg <- fn.gen[nm,]
      rt <- rtt[nm,]
      tr <- fn.tr[,nm]
      
      dem <- fn.tr$demGW          # demand trace
      rt$IC <- max.nem - grn      # required capacity
      
      use <- round(sum(pmin(dem, rt$IC * tr)),digits=10) # actual demand consumed
      rt$Prop <- round(sum(use) / fn.var$dem, digits=10) # proportion  = total consumption / demand
      rt$CF <- round((use * sg$avail) / (rt$IC * fn.var$hr), digits=10) # market capacity factor
      rt$LCOE <- round((sg$lcoe*(sg$cf/rt$CF)) + (sg$fuel.cost+(fn.var$c.price*sg$co2))*rt$CF/sg$cf, digits=10)
      
      gap <- pmax(0, dem - rt$IC * tr)
      rtt[nm, ] <- rt
      
      modrt <- fn_renopt(incr=grn, gap=gap, prec=fn.var$opt, fn.tr = fn.tr) # call fn_renopt
      
      w.prop <- modrt$w.prop; win.use <- modrt$win.use; sol.use <- modrt$sol.use; ren.gap <- modrt$ren.gap
      
      rtt['wind',]$IC <- grn*w.prop
      rtt['wind',]$Prop <- sum(win.use)/fn.var$dem
      rtt['wind',]$CF<- (sum(win.use) * fn.gen['wind',]$avail)/(rtt['wind', ]$IC*fn.var$hr)
      rtt['wind',]$LCOE <- round((fn.gen['wind',]$lcoe*(fn.gen['wind',]$cf/rtt['wind',]$CF)),10)
      
      rtt['solar',]$IC <- grn*(1 - w.prop)
      rtt['solar',]$Prop <- sum(sol.use)/fn.var$dem
      rtt['solar',]$CF<- (sum(sol.use)*fn.gen['solar',]$avail)/(rtt['solar', ]$IC*fn.var$hr)
      rtt['solar',]$LCOE <- round((fn.gen['solar',]$lcoe*(fn.gen['solar',]$cf/rtt['solar',]$CF)),10)
      
      gap <- ren.gap
    }
    # residual demand is always met by OC gas
    rt <- rtt['gas',]
    gg <- fn.gen['gas',]
    
    rt$IC <- max(gap)
    rt$Prop <- round(sum(gap) / fn.var$dem,digits=10)
    rt$CF <- round((sum(gap)*gg$avail) / (rt$IC * fn.var$hr),digits=10)
    rt$LCOE <-  round((gg$lcoe*(gg$cf/rt$CF)) + (gg$fuel.cost+(fn.var$c.price*gg$co2))*rt$CF/gg$cf,digits=10)
    
    rtt['gas',] <- rt
    
    av.lcoe <- round(sum(rtt$Prop * rtt$LCOE, na.rm=T),10)
    CO2.MWh <- round(rtt['gas',]$Prop * gg$co2,10)
    if(is.na(fn.gen['ccgt',1]) == F) CO2.MWh <- CO2.MWh + round(rt$Prop*sg$co2,10) # add ccgt EI if in mix
 
    rtt <- unlist(rtt)
    names(rtt) <- rn
    rtt <- c(rtt, av.lcoe = av.lcoe, CO2.MWh = CO2.MWh)
    return(rtt)   
  })
    rt <- t(rt)  
    return(as.data.frame(rt))
}
