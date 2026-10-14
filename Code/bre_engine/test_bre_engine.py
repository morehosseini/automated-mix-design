"""Unit tests for the BRE mix design engine. Run: python3 test_bre_engine.py"""
import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from bre_mix_design import (AggregateMoisture, BREInput, design_mix,
                            fine_fraction, free_water, slump_band,
                            wc_from_strength, wet_density)

FAIL = []


def check(name, cond, detail=""):
    status = "ok" if cond else "FAIL"
    print(f"  [{status}] {name} {detail}")
    if not cond:
        FAIL.append(name)


print("slump band mapping")
check("0-10", slump_band(5) == "0-10")
check("10-30 upper edge", slump_band(30) == "10-30")
check("range tuple", slump_band((10, 30)) == "10-30")
check("100 mm -> 60-180", slump_band(100) == "60-180")

print("Table 3 water")
check("same types", free_water(40, "30-60", "uncrushed", "uncrushed") == 160)
check("2/3-1/3 rule", abs(free_water(40, "10-30", "uncrushed", "crushed")
                          - (2 * 140 + 175) / 3) < 1e-9)
check("Ex3 case", abs(free_water(20, "60-180", "crushed", "uncrushed")
                      - (2 * 225 + 195) / 3) < 1e-9)

print("Figure 2 (w/c from strength)")
wc45, s05 = wc_from_strength(45, 42.5, "crushed")
check("Ex1 read", abs(wc45 - 0.53) <= 0.02, f"(wc={wc45:.3f})")
check("anchor point", abs(wc_from_strength(49, 42.5, "crushed")[0] - 0.5) < 1e-9)
wc_a = wc_from_strength(30, 42.5, "uncrushed")[0]
wc_b = wc_from_strength(40, 42.5, "uncrushed")[0]
check("monotone decreasing", wc_a > wc_b)

print("Figure 3 (wet density)")
check("Ex1 read", abs(wet_density(2.65, 151) - 2450) <= 15)
check("more water -> lighter", wet_density(2.65, 220) < wet_density(2.65, 150))
check("higher SG -> heavier", wet_density(2.8, 180) > wet_density(2.5, 180))

print("Figure 4 (fine fraction)")
p1 = fine_fraction(40, "10-30", 0.5, 70)
check("Ex1 read", abs(p1 - 22) <= 2.5, f"(p={p1:.1f})")
check("coarser sand -> more fines",
      fine_fraction(20, "30-60", 0.5, 15) > fine_fraction(20, "30-60", 0.5, 100))
check("wetter mix -> more fines",
      fine_fraction(20, "60-180", 0.5, 60) > fine_fraction(20, "0-10", 0.5, 60))
check("smaller agg -> more fines",
      fine_fraction(10, "30-60", 0.5, 60) > fine_fraction(40, "30-60", 0.5, 60))

print("solver behaviour")
base = dict(target_mean=45, cement_class=42.5, coarse_type="crushed",
            fine_type="uncrushed", slump_mm=(10, 30), max_agg_mm=40,
            fines_passing_600um_pct=70, agg_sg_ssd=2.65)
r = design_mix(BREInput(**base, wc_max=0.50))
check("durability cap governs", abs(r.wc_used - 0.50) < 1e-9)
r2 = design_mix(BREInput(**base))
check("no cap -> curve value", abs(r2.wc_used - r2.wc_curve) < 1e-9)
r3 = design_mix(BREInput(**base, wc_max=0.50, cement_min=350))
check("min cement enforced", abs(r3.cement - 350) < 1e-9)
check("modified w/c recorded", r3.wc_modified is not None
      and abs(r3.wc_modified - r3.water / 350) < 1e-9)
check("volume balance", abs(r.wet_density - (r.cement + r.water
                                             + r.total_aggregate)) < 1e-6)

print("QA / target strength")
rq = design_mix(BREInput(fck=30, defectives_pct=5.0, n_results=0, **{
    k: v for k, v in base.items() if k != "target_mean"}))
check("fm = fck + 1.64*8", abs(rq.target_mean - (30 + 1.64 * 8)) < 1e-9)
rm = design_mix(BREInput(fck=25, margin=10, **{
    k: v for k, v in base.items() if k != "target_mean"}))
check("specified margin", abs(rm.target_mean - 35) < 1e-9)

print("moisture correction")
rmc = design_mix(BREInput(**base, wc_max=0.50,
                          fine_moisture=AggregateMoisture(1.0, 2.0),
                          coarse_moisture=AggregateMoisture(1.5, 2.0)))
check("moist fine > SSD", rmc.fine_moist > rmc.fine_ssd)
check("adjusted water < free water", rmc.water_adjusted < rmc.water)
tot_w = (rmc.water_adjusted + (rmc.fine_moist - rmc.fine_ssd)
         + (rmc.coarse_moist - rmc.coarse_ssd))
check("water mass conserved", abs(tot_w - rmc.water) < 1e-6)

print("multi-coarse split")
rs = design_mix(BREInput(**base, wc_max=0.50,
                         coarse_ratios={10: 1, 20: 1.5, 40: 3}))
check("split sums to coarse total",
      abs(sum(rs.coarse_split_ssd.values()) - rs.coarse_ssd) < 1e-6)
check("ratio proportions", abs(rs.coarse_split_ssd[40]
                               / rs.coarse_split_ssd[10] - 3.0) < 1e-9)

print("trial mix scaling")
rt = design_mix(BREInput(**base, wc_max=0.50, trial_volume_m3=0.05))
check("cement scaled", abs(rt.trial_quantities["cement"]
                           - 0.05 * rt.cement) < 1e-9)

print("cement_max constraint (T0.2: BRE handbook Section 7.4 'Example 4: "
      "mix restricted by maximum cement content' - fck=50@7d, RHPC 52.5, "
      "crushed 10mm single-size, previous SD=5, defectives 1%, max cement "
      "550 kg/m3; the handbook's own worked answer is that the design AS "
      "SPECIFIED IS INFEASIBLE - required cement 580 kg/m3 > 550 kg/m3 max "
      "- so the design form is left incomplete beyond Stage 3. This checks "
      "the engine reproduces that same infeasibility finding and warns, "
      "rather than silently returning an over-cement mix.")
rcm = design_mix(BREInput(
    fck=50, defectives_pct=1.0, sd=5.0, age_days=7,
    cement_class=52.5, coarse_type="crushed", fine_type="uncrushed",
    slump_mm=(30, 60), max_agg_mm=10, fines_passing_600um_pct=45,
    agg_sg_ssd=2.7, cement_max=550))
check("target mean = fck + 2.33*5", abs(rcm.target_mean - (50 + 2.33 * 5)) < 1e-9,
      f"(fm={rcm.target_mean:.2f}, handbook rounds to 62)")
check("free w/c matches handbook chart reading",
      abs(rcm.wc_curve - 0.37) <= 0.02, f"(wc={rcm.wc_curve:.3f})")
check("free water within handbook's Table-3 2/3-1/3 blend (215, rounded to "
      "nearest 5)", abs(rcm.water - 215) <= 5, f"(water={rcm.water:.1f})")
check("cement content exceeds specified maximum (design infeasible)",
      rcm.cement > 550,
      f"(cement={rcm.cement:.1f} vs max 550, handbook: 580)")
check("engine raises a maximum-cement-content warning",
      any("maximum" in w_.lower() for w_ in rcm.warnings), f"{rcm.warnings}")

print()
if FAIL:
    print(f"{len(FAIL)} TEST(S) FAILED: {FAIL}")
    sys.exit(1)
print("All tests passed.")
