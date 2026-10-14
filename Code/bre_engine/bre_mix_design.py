"""
BRE/DOE concrete mix design engine
==================================

Automated implementation of the BRE 'Design of Normal Concrete Mixes'
(2nd ed., 1997) procedure, as taught in the course materials reproduced in
`sources/Concrete Mix Design_Workings Included.pdf` and
`sources/Supplementary Materials.pdf`.

Data provenance
---------------
* Table 1 (probability factor K) and Table 2 (approximate strength at
  w/c = 0.5) - transcribed exactly from the supplementary materials.
* Table 3 (free-water content) - transcribed exactly.
* Figure 2 (strength vs free-w/c curve family) - DIGITIZED (T0.1, R03.1):
  all 9 printed curves programmatically extracted (see digitize_fig2.py;
  audit overlay qa_overlays/qa2_fig2_strength.png) and pooled into a single
  fixed-effects OLS regression ln(S) = intercept_k + slope*wc across ~19,000
  points, giving a chart-derived Abrams exponent ln(B) = 2.9996
  (data/fig2_strength_wc_digitized.json). The model form is unchanged
  (S(wc) = S05 * B**(0.5 - wc), anchored at the user's Table-2 S05), only the
  exponent is now fitted to the whole curve family rather than 3 points.
  Validated against the three instructor chart readings: max deviation 0.018
  (within the +/-0.02 chart-reading tolerance). The original 3-point-anchored
  value (ln B = 2.7739) is retained as an explicit fallback/override
  (`model="anchor"` in `wc_from_strength`) for sensitivity checks.
* Figure 3 (wet density) and Figure 4 (proportion of fine aggregate) -
  digitized programmatically from the scanned charts (see digitize_fig3.py
  and digitize_fig4_v2.py; audit overlays in qa_overlays/). Linear models
  per curve; interpolation between curves.

All intermediate steps are recorded in a calculation log (result.log) for
traceability ('show your work' output).

Units: strengths N/mm2 (MPa); masses kg/m3; water kg/m3 (== L/m3);
slump mm; aggregate sizes mm.
"""
from __future__ import annotations

import json
import math
import os
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

_DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")

# ----------------------------------------------------------------------
# Exact tables (transcribed from supplementary materials)
# ----------------------------------------------------------------------

TABLE1_K = {10.0: 1.28, 5.0: 1.64, 2.5: 1.96, 1.0: 2.33}  # % defective -> K

# Table 2: approximate compressive strength (N/mm2) at free-w/c = 0.5
# key: (cement_class, coarse_type) -> {age_days: strength}
TABLE2_S05 = {
    (42.5, "uncrushed"): {3: 22, 7: 30, 28: 42, 91: 49},
    (42.5, "crushed"):   {3: 27, 7: 36, 28: 49, 91: 56},
    (52.5, "uncrushed"): {3: 29, 7: 37, 28: 48, 91: 54},
    (52.5, "crushed"):   {3: 34, 7: 43, 28: 55, 91: 61},
}

# Table 3: approximate free-water content (kg/m3) for workability
# key: max_agg_mm -> agg_type -> slump band -> water
SLUMP_BANDS = ["0-10", "10-30", "30-60", "60-180"]
TABLE3_WATER = {
    10: {"uncrushed": {"0-10": 150, "10-30": 180, "30-60": 205, "60-180": 225},
         "crushed":   {"0-10": 180, "10-30": 205, "30-60": 230, "60-180": 250}},
    20: {"uncrushed": {"0-10": 135, "10-30": 160, "30-60": 180, "60-180": 195},
         "crushed":   {"0-10": 170, "10-30": 190, "30-60": 210, "60-180": 225}},
    40: {"uncrushed": {"0-10": 115, "10-30": 140, "30-60": 160, "60-180": 175},
         "crushed":   {"0-10": 155, "10-30": 175, "30-60": 190, "60-180": 205}},
}

# Figure 2 model: S(wc) = S05 * B ** (0.5 - wc). Two exponents are kept:
#   "digitized" (default) - chart-derived, fitted to all 9 printed curves
#   "anchor"    (fallback) - the original 3-instructor-reading estimate
LN_B_ANCHOR_FALLBACK = 2.7739

# Figure 1 (standard deviation vs characteristic strength), simplified:
SD_FEWER_THAN_20_RESULTS = 8.0   # for fck >= 20 MPa
SD_MIN_20_OR_MORE = 4.0


def _load_json(name):
    with open(os.path.join(_DATA_DIR, name)) as f:
        return json.load(f)


_FIG6 = _load_json("fig6_fine_fraction_digitized.json")     # fine agg proportion
_FIG5 = _load_json("fig5_wet_density_digitized.json")       # wet density
_FIG2 = _load_json("fig2_strength_wc_digitized.json")       # strength vs w/c

LN_B_DIGITIZED = _FIG2["ln_b_chart"]
LN_B = LN_B_DIGITIZED  # default exponent used by wc_from_strength()


# ----------------------------------------------------------------------
# Chart lookups
# ----------------------------------------------------------------------

def slump_band(slump_mm) -> str:
    """Map a slump value or '(lo, hi)' range to a Table 3 / Figure 4 band."""
    if isinstance(slump_mm, (tuple, list)):
        lo, hi = slump_mm
        for band in SLUMP_BANDS:
            b_lo, b_hi = (int(v) for v in band.split("-"))
            if lo >= b_lo and hi <= b_hi:
                return band
        slump_mm = 0.5 * (lo + hi)
    s = float(slump_mm)
    if s <= 10:
        return "0-10"
    if s <= 30:
        return "10-30"
    if s <= 60:
        return "30-60"
    return "60-180"


def wc_from_strength(target_mean: float, cement_class: float, coarse_type: str,
                     age_days: int = 28,
                     model: str = "digitized") -> Tuple[float, float]:
    """Figure 2: free-w/c ratio for a target mean strength.
    Returns (wc, S05). S(wc) = S05 * B**(0.5 - wc), anchored at the user's
    Table-2 S05.  model='digitized' (default) uses the chart-derived exponent
    fitted to all 9 printed curves (see module docstring); model='anchor'
    uses the original 3-point-anchored exponent, retained for sensitivity
    checks / as a documented fallback."""
    key = (float(cement_class), coarse_type.lower())
    if key not in TABLE2_S05:
        raise ValueError(f"No Table 2 entry for {key}")
    ages = TABLE2_S05[key]
    if age_days not in ages:
        raise ValueError(f"Age {age_days} not in Table 2 (use {list(ages)})")
    s05 = ages[age_days]
    if model == "digitized":
        ln_b = LN_B_DIGITIZED
    elif model == "anchor":
        ln_b = LN_B_ANCHOR_FALLBACK
    else:
        raise ValueError("model must be 'digitized' or 'anchor'")
    wc = 0.5 + math.log(s05 / target_mean) / ln_b
    return wc, s05


def free_water(max_agg_mm: int, band: str, fine_type: str, coarse_type: str) -> float:
    """Table 3 with the BRE combination rule W = (2*Wf + Wc)/3 when fine and
    coarse aggregate types differ (Wf/Wc = water for the fine/coarse type)."""
    tbl = TABLE3_WATER[int(max_agg_mm)]
    wf = tbl[fine_type.lower()][band]
    wcoarse = tbl[coarse_type.lower()][band]
    if fine_type.lower() == coarse_type.lower():
        return float(wf)
    return (2.0 * wf + 1.0 * wcoarse) / 3.0


def wet_density(agg_sg_ssd: float, water: float) -> float:
    """Figure 3 (digitized): wet density of compacted concrete (kg/m3)."""
    sgs = sorted(float(s) for s in _FIG5 if _FIG5[s])
    vals = {s: _FIG5[str(s)]["a"] + _FIG5[str(s)]["b"] * water for s in sgs}
    sg = min(max(agg_sg_ssd, sgs[0]), sgs[-1])
    for lo, hi in zip(sgs, sgs[1:]):
        if lo <= sg <= hi:
            t = (sg - lo) / (hi - lo)
            return vals[lo] + t * (vals[hi] - vals[lo])
    return vals[sgs[0]]


def fine_fraction(max_agg_mm: int, band: str, wc: float,
                  passing_600um_pct: float) -> float:
    """Figure 4 (digitized): recommended proportion of fine aggregate (%),
    interpolating between the 15/40/60/80/100 %-passing curves."""
    panel = _FIG6[str(int(max_agg_mm))][band]
    labs = [int(l) for l in ("15", "40", "60", "80", "100") if panel.get(l)]
    vals = {l: panel[str(l)]["a"] + panel[str(l)]["b"] * wc for l in labs}
    p = passing_600um_pct
    if p <= labs[0]:
        return vals[labs[0]]
    if p >= labs[-1]:
        return vals[labs[-1]]
    for lo, hi in zip(labs, labs[1:]):
        if lo <= p <= hi:
            t = (p - lo) / (hi - lo)
            return vals[lo] + t * (vals[hi] - vals[lo])
    raise RuntimeError("unreachable")


# ----------------------------------------------------------------------
# Input / result models
# ----------------------------------------------------------------------

@dataclass
class AggregateMoisture:
    absorption_pct: float = 0.0      # water absorption WA (%)
    total_moisture_pct: float = 0.0  # total moisture content MC (%)


@dataclass
class BREInput:
    # strength requirement (give either target_mean OR fck [+ margin or QA data])
    fck: Optional[float] = None
    target_mean: Optional[float] = None
    margin: Optional[float] = None            # specified margin (N/mm2)
    defectives_pct: float = 5.0               # -> K via Table 1
    sd: Optional[float] = None                # standard deviation if known
    n_results: int = 0                        # number of prior test results
    age_days: int = 28

    cement_class: float = 42.5
    coarse_type: str = "crushed"              # 'crushed' | 'uncrushed'
    fine_type: str = "uncrushed"

    slump_mm: object = 50                     # value or (lo, hi)
    max_agg_mm: int = 20
    fines_passing_600um_pct: float = 60.0
    agg_sg_ssd: Optional[float] = None        # combined SSD relative density

    wc_max: Optional[float] = None            # durability cap
    cement_min: Optional[float] = None        # kg/m3
    cement_max: Optional[float] = None        # kg/m3

    # coarse aggregate blend ratios by size, e.g. {10: 1, 20: 1.5, 40: 3}
    coarse_ratios: Optional[Dict[int, float]] = None

    # site condition (moisture correction)
    fine_moisture: Optional[AggregateMoisture] = None
    coarse_moisture: Optional[AggregateMoisture] = None

    trial_volume_m3: Optional[float] = None

    # validation overrides (Tier-1 arithmetic checks): force chart readings
    override_wc_curve: Optional[float] = None
    override_density: Optional[float] = None
    override_fine_pct: Optional[float] = None


@dataclass
class BREResult:
    target_mean: float = 0.0
    wc_curve: float = 0.0          # from Fig 2 (before durability cap)
    wc_used: float = 0.0
    wc_modified: Optional[float] = None
    water: float = 0.0             # free water, kg/m3
    cement: float = 0.0            # kg/m3
    wet_density: float = 0.0
    total_aggregate: float = 0.0
    fine_pct: float = 0.0
    fine_ssd: float = 0.0
    coarse_ssd: float = 0.0
    coarse_split_ssd: Dict[int, float] = field(default_factory=dict)
    # site-condition (moist) batch quantities
    fine_moist: Optional[float] = None
    coarse_moist: Optional[float] = None
    coarse_split_moist: Optional[Dict[int, float]] = None
    water_adjusted: Optional[float] = None
    trial_quantities: Optional[Dict[str, float]] = None
    warnings: List[str] = field(default_factory=list)
    log: List[str] = field(default_factory=list)


# ----------------------------------------------------------------------
# Main solver
# ----------------------------------------------------------------------

def design_mix(inp: BREInput) -> BREResult:
    r = BREResult()
    L = r.log.append

    # ---- Step 1: target mean strength ----
    if inp.target_mean is not None:
        r.target_mean = float(inp.target_mean)
        L(f"Step 1: target mean strength specified: fm = {r.target_mean:.1f} N/mm2")
    elif inp.fck is not None and inp.margin is not None:
        r.target_mean = inp.fck + inp.margin
        L(f"Step 1: fm = fck + specified margin = {inp.fck:.1f} + {inp.margin:.1f} "
          f"= {r.target_mean:.1f} N/mm2")
    elif inp.fck is not None:
        if inp.defectives_pct not in TABLE1_K:
            raise ValueError(f"defectives_pct must be one of {list(TABLE1_K)}")
        k = TABLE1_K[inp.defectives_pct]
        sd = inp.sd
        if sd is None:
            sd = (SD_MIN_20_OR_MORE if inp.n_results >= 20
                  else SD_FEWER_THAN_20_RESULTS)
            L(f"Step 1: SD not given; Figure 1 default s = {sd:.1f} N/mm2 "
              f"({inp.n_results} prior results)")
        r.target_mean = inp.fck + k * sd
        L(f"Step 1: fm = fck + K*s = {inp.fck:.1f} + {k:.2f}*{sd:.1f} "
          f"= {r.target_mean:.1f} N/mm2  (Table 1: {inp.defectives_pct}% defective)")
    else:
        raise ValueError("Provide target_mean, or fck (+ margin / QA data)")

    # ---- Step 2: free-w/c ratio ----
    if inp.override_wc_curve is not None:
        r.wc_curve = inp.override_wc_curve
        _, s05 = wc_from_strength(r.target_mean, inp.cement_class,
                                  inp.coarse_type, inp.age_days)
        L(f"Step 2: w/c from chart OVERRIDDEN to {r.wc_curve:.2f} "
          f"(Table 2 S05 = {s05} N/mm2)")
    else:
        r.wc_curve, s05 = wc_from_strength(r.target_mean, inp.cement_class,
                                           inp.coarse_type, inp.age_days)
        L(f"Step 2: Table 2 S05 = {s05} N/mm2 ({inp.cement_class} class, "
          f"{inp.coarse_type} coarse, {inp.age_days} d); Figure 2 (Abrams-type, "
          f"ln B = {LN_B}) -> w/c = {r.wc_curve:.3f}")
    r.wc_used = r.wc_curve
    if inp.wc_max is not None and inp.wc_max < r.wc_used:
        r.wc_used = inp.wc_max
        L(f"Step 2: durability cap governs: use lower of ({r.wc_curve:.3f}, "
          f"{inp.wc_max:.2f}) -> w/c = {r.wc_used:.3f}")

    # ---- Step 3: free-water content ----
    band = slump_band(inp.slump_mm)
    r.water = free_water(inp.max_agg_mm, band, inp.fine_type, inp.coarse_type)
    wf = TABLE3_WATER[inp.max_agg_mm][inp.fine_type.lower()][band]
    wcrs = TABLE3_WATER[inp.max_agg_mm][inp.coarse_type.lower()][band]
    if inp.fine_type.lower() == inp.coarse_type.lower():
        L(f"Step 3: Table 3 ({inp.max_agg_mm} mm, slump {band} mm, "
          f"{inp.fine_type}): W = {r.water:.1f} kg/m3")
    else:
        L(f"Step 3: Table 3 ({inp.max_agg_mm} mm, slump {band} mm): "
          f"W = (2*{wf} + {wcrs})/3 = {r.water:.1f} kg/m3 "
          f"(2/3 fine-type + 1/3 coarse-type rule)")

    # ---- Step 4: cement content ----
    r.cement = r.water / r.wc_used
    L(f"Step 4: C = W / (w/c) = {r.water:.1f} / {r.wc_used:.3f} "
      f"= {r.cement:.1f} kg/m3")
    if inp.cement_max is not None and r.cement > inp.cement_max:
        r.warnings.append(
            f"Cement content {r.cement:.0f} exceeds specified maximum "
            f"{inp.cement_max:.0f} kg/m3 - specification conflict.")
        L(f"Step 4: WARNING - C exceeds maximum {inp.cement_max:.0f} kg/m3")
    if inp.cement_min is not None and r.cement < inp.cement_min:
        r.cement = inp.cement_min
        r.wc_modified = r.water / r.cement
        r.wc_used = r.wc_modified
        L(f"Step 4: C below specified minimum -> use C = {r.cement:.1f} kg/m3; "
          f"modified free-w/c = {r.wc_modified:.3f}")

    # ---- Step 5: total aggregate content ----
    if inp.agg_sg_ssd is not None:
        sg = inp.agg_sg_ssd
        sg_src = "known/assumed"
    else:
        sg = 2.7 if inp.coarse_type.lower() == "crushed" else 2.6
        sg_src = f"BRE default for {inp.coarse_type} aggregate"
    if inp.override_density is not None:
        r.wet_density = inp.override_density
        L(f"Step 5: wet density OVERRIDDEN to {r.wet_density:.0f} kg/m3")
    else:
        r.wet_density = wet_density(sg, r.water)
        L(f"Step 5: Figure 3 (digitized): D = {r.wet_density:.0f} kg/m3 "
          f"(SSD relative density {sg} [{sg_src}], W = {r.water:.1f})")
    r.total_aggregate = r.wet_density - r.cement - r.water
    L(f"Step 5: TA = D - C - W = {r.wet_density:.0f} - {r.cement:.1f} - "
      f"{r.water:.1f} = {r.total_aggregate:.1f} kg/m3")

    # ---- Step 6: fine / coarse aggregate ----
    if inp.override_fine_pct is not None:
        r.fine_pct = inp.override_fine_pct
        L(f"Step 6: fine aggregate proportion OVERRIDDEN to {r.fine_pct:.1f}%")
    else:
        r.fine_pct = fine_fraction(inp.max_agg_mm, band, r.wc_used,
                                   inp.fines_passing_600um_pct)
        L(f"Step 6: Figure 4 (digitized, {inp.max_agg_mm} mm, slump {band}, "
          f"w/c {r.wc_used:.2f}, {inp.fines_passing_600um_pct:.0f}% passing "
          f"600 um) -> {r.fine_pct:.1f}%")
    r.fine_ssd = r.total_aggregate * r.fine_pct / 100.0
    r.coarse_ssd = r.total_aggregate - r.fine_ssd
    L(f"Step 6: fine = {r.total_aggregate:.0f} * {r.fine_pct:.1f}% "
      f"= {r.fine_ssd:.1f} kg/m3 (SSD); coarse = {r.coarse_ssd:.1f} kg/m3 (SSD)")

    # coarse split - explicit ratios required for blends (no silent equal split)
    if inp.coarse_ratios:
        tot = sum(inp.coarse_ratios.values())
        r.coarse_split_ssd = {sz: r.coarse_ssd * f / tot
                              for sz, f in sorted(inp.coarse_ratios.items())}
        L("Step 6: coarse split " +
          ":".join(str(v) for _, v in sorted(inp.coarse_ratios.items())) +
          " -> " + ", ".join(f"{sz} mm: {m:.1f}"
                             for sz, m in r.coarse_split_ssd.items()))
    else:
        r.coarse_split_ssd = {inp.max_agg_mm: r.coarse_ssd}

    # ---- Step 7: moisture correction (site condition) ----
    if inp.fine_moisture or inp.coarse_moisture:
        fm = inp.fine_moisture or AggregateMoisture()
        cm = inp.coarse_moisture or AggregateMoisture()
        f_fac = 1.0 + (fm.total_moisture_pct - fm.absorption_pct) / 100.0
        c_fac = 1.0 + (cm.total_moisture_pct - cm.absorption_pct) / 100.0
        r.fine_moist = r.fine_ssd * f_fac
        r.coarse_moist = r.coarse_ssd * c_fac
        r.coarse_split_moist = {sz: m * c_fac
                                for sz, m in r.coarse_split_ssd.items()}
        surf_f = r.fine_moist - r.fine_ssd
        surf_c = r.coarse_moist - r.coarse_ssd
        r.water_adjusted = r.water - surf_f - surf_c
        L(f"Step 7: moisture correction - fine x{f_fac:.3f} "
          f"(MC {fm.total_moisture_pct}%, WA {fm.absorption_pct}%), "
          f"coarse x{c_fac:.3f} (MC {cm.total_moisture_pct}%, "
          f"WA {cm.absorption_pct}%)")
        L(f"Step 7: batch masses - fine {r.fine_moist:.1f}, "
          f"coarse {r.coarse_moist:.1f} kg/m3; surface water "
          f"{surf_f:.1f} + {surf_c:.1f} kg -> adjusted water "
          f"= {r.water:.1f} - {surf_f:.1f} - {surf_c:.1f} "
          f"= {r.water_adjusted:.1f} kg/m3")

    # ---- Step 8: trial mix scaling ----
    if inp.trial_volume_m3:
        v = inp.trial_volume_m3
        q = {"cement": r.cement * v,
             "water": (r.water_adjusted if r.water_adjusted is not None
                       else r.water) * v,
             "fine": (r.fine_moist if r.fine_moist is not None
                      else r.fine_ssd) * v}
        split = (r.coarse_split_moist if r.coarse_split_moist is not None
                 else r.coarse_split_ssd)
        for sz, m in split.items():
            q[f"coarse_{sz}mm"] = m * v
        r.trial_quantities = q
        L(f"Step 8: trial mix ({v} m3): " +
          ", ".join(f"{k} = {m:.1f} kg" for k, m in q.items()))

    # ---- sanity checks ----
    if r.total_aggregate <= 0:
        r.warnings.append("Total aggregate content non-positive - inputs invalid.")
    if not (0.3 <= r.wc_used <= 0.9):
        r.warnings.append(f"w/c {r.wc_used:.2f} outside chart range 0.3-0.9.")
    if r.water_adjusted is not None and r.water_adjusted < 0:
        r.warnings.append("Adjusted water negative - check moisture inputs.")
    return r


def print_report(r: BREResult):
    print("=" * 64)
    print("BRE MIX DESIGN - CALCULATION RECORD")
    print("=" * 64)
    for line in r.log:
        print(" ", line)
    if r.warnings:
        print("WARNINGS:")
        for w_ in r.warnings:
            print("  !", w_)
    print("-" * 64)
    print(f"  Per m3 (SSD basis): cement {r.cement:.0f} | water {r.water:.0f} "
          f"| fine {r.fine_ssd:.0f} | coarse {r.coarse_ssd:.0f} kg")
    if r.coarse_split_ssd and len(r.coarse_split_ssd) > 1:
        print("  Coarse split (SSD):",
              ", ".join(f"{sz} mm: {m:.0f} kg" for sz, m in r.coarse_split_ssd.items()))
    if r.water_adjusted is not None:
        print(f"  Site batch (moist): fine {r.fine_moist:.0f} | "
              f"coarse {r.coarse_moist:.0f} | water {r.water_adjusted:.0f} kg")
