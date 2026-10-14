"""
Validation of the BRE mix design engine against instructor-worked examples
(sources/Example_01..03_Answer.pdf) plus, from T0.2, one additional example
transcribed directly from the primary source itself - the BRE handbook
"Design of Normal Concrete Mixes" (2nd ed., 1997), Section 7.1 "Example 1:
unrestricted design" (see DEV_LOG.md 2026-07-24 T0.2 entry for provenance
and the two independent web mirrors that corroborate it).

Two tiers:
  Tier 1 (arithmetic): the engine is forced to use the instructor's own chart
      readings (w/c from Fig 2, density from Fig 3, fine % from Fig 4).
      Any residual error isolates the arithmetic/logic of the pipeline.
  Tier 2 (fully automated): all chart values come from the digitized models.
      Residuals then include chart-digitization differences; acceptance
      criterion: every mass within +/-3% or +/-15 kg/m3 of the reference.

Outputs: validation_results.csv + console table.
"""
import csv
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from bre_mix_design import AggregateMoisture, BREInput, design_mix

# ----------------------------------------------------------------------
# Reference values transcribed from the answer PDFs (per m3, SSD basis)
# ----------------------------------------------------------------------
EXAMPLES = {
    "Ex1": {
        "input": BREInput(
            target_mean=45, age_days=28, cement_class=42.5,
            coarse_type="crushed", fine_type="uncrushed",
            slump_mm=(10, 30), max_agg_mm=40, fines_passing_600um_pct=70,
            agg_sg_ssd=2.65, wc_max=0.50, cement_min=300,
            coarse_ratios={10: 1, 20: 1.5, 40: 3},
            fine_moisture=AggregateMoisture(absorption_pct=1.0, total_moisture_pct=2.0),
            coarse_moisture=AggregateMoisture(absorption_pct=1.5, total_moisture_pct=2.0),
            trial_volume_m3=0.05,
        ),
        "instructor_readings": {"wc_curve": 0.53, "density": 2450, "fine_pct": 22.0},
        "reference": {"wc_used": 0.50, "water": 151, "cement": 302,
                      "density": 2450, "total_agg": 1997, "fine": 439,
                      "coarse": 1558, "coarse_10": 283, "coarse_20": 425,
                      "coarse_40": 850},
        "reference_trial": {"cement": 15, "water": 8, "fine": 22,
                            "coarse_10": 14, "coarse_20": 21, "coarse_40": 42},
    },
    "Ex2": {
        "input": BREInput(
            fck=25, margin=10, age_days=28, cement_class=42.5,
            coarse_type="uncrushed", fine_type="uncrushed",
            slump_mm=(30, 60), max_agg_mm=40, fines_passing_600um_pct=90,
            agg_sg_ssd=2.5, wc_max=0.50, cement_min=290,
            coarse_ratios={10: 1, 20: 1.5, 40: 3},
            trial_volume_m3=0.08,
        ),
        "instructor_readings": {"wc_curve": 0.55, "density": 2330, "fine_pct": 22.0},
        "reference": {"wc_used": 0.50, "water": 160, "cement": 320,
                      "density": 2330, "total_agg": 1850, "fine": 407,
                      "coarse": 1443, "coarse_10": 262, "coarse_20": 393,
                      "coarse_40": 786},
        "reference_trial": {"cement": 26, "water": 13, "fine": 33,
                            "coarse_10": 21, "coarse_20": 32, "coarse_40": 64},
    },
    "Ex3": {
        "input": BREInput(
            target_mean=30, age_days=28, cement_class=42.5,
            coarse_type="uncrushed", fine_type="crushed",
            slump_mm=100, max_agg_mm=20, fines_passing_600um_pct=50,
            agg_sg_ssd=2.65, wc_max=0.45, cement_min=300,
            coarse_ratios={10: 1, 20: 2},
            fine_moisture=AggregateMoisture(absorption_pct=2.0, total_moisture_pct=2.0),
            coarse_moisture=AggregateMoisture(absorption_pct=1.5, total_moisture_pct=2.0),
            trial_volume_m3=0.16,
        ),
        "instructor_readings": {"wc_curve": 0.63, "density": 2375, "fine_pct": 40.0},
        "reference": {"wc_used": 0.45, "water": 215, "cement": 478,
                      "density": 2375, "total_agg": 1682, "fine": 673,
                      "coarse": 1009, "coarse_10": 336, "coarse_20": 672},
        "reference_trial": {},
    },
    # --- Added T0.2 (2026-07-24): BRE handbook's own worked example -------
    # Source: "Design of Normal Concrete Mixes" (BRE, 2nd ed. 1997),
    # Section 7.1 "Example 1: unrestricted design", Table 4. This is the
    # method's own primary-source example (not a third-party re-derivation),
    # transcribed from a full-text mirror of the handbook (academia.edu
    # "Design_of_normal_concrete_mixes_BRE") and cross-checked word-for-word
    # against two independent university course re-hostings of the same
    # example (EMU CIVL284 "BRE Mix Design Example 1.pdf"; a studylib.net
    # course pack citing "Source: Building Research Establishment"). All
    # three sources agree on every input and every output value below.
    # No moisture data is given for this example in the source (a separate,
    # differently-conventioned oven-dry illustration is appended to it in
    # the handbook and is not used here), so no moisture correction is
    # exercised by this case - Ex1/Ex3 already cover that path.
    "Ex4": {
        "input": BREInput(
            fck=30, defectives_pct=2.5, n_results=0, age_days=28,
            cement_class=42.5, coarse_type="uncrushed", fine_type="uncrushed",
            slump_mm=(10, 30), max_agg_mm=20, fines_passing_600um_pct=70,
            agg_sg_ssd=2.6, wc_max=0.55, cement_min=290,
            coarse_ratios={10: 1, 20: 2},
            trial_volume_m3=0.05,
        ),
        "instructor_readings": {"wc_curve": 0.47, "density": 2400, "fine_pct": 27.0},
        "reference": {"wc_used": 0.47, "water": 160, "cement": 340,
                      "density": 2400, "total_agg": 1900, "fine": 515,
                      "coarse": 1385, "coarse_10": 460, "coarse_20": 925},
        "reference_trial": {"cement": 17.0, "water": 8.0, "fine": 25.7,
                            "coarse_10": 23.0, "coarse_20": 46.2},
    },
}


def extract(res, ref):
    got = {"wc_used": res.wc_used, "water": res.water, "cement": res.cement,
           "density": res.wet_density, "total_agg": res.total_aggregate,
           "fine": res.fine_ssd, "coarse": res.coarse_ssd}
    for sz, m in res.coarse_split_ssd.items():
        got[f"coarse_{sz}"] = m
    return {k: got[k] for k in ref}


def run(tier: int):
    rows = []
    for name, ex in EXAMPLES.items():
        inp = ex["input"]
        if tier == 1:
            rd = ex["instructor_readings"]
            inp2 = BREInput(**{**inp.__dict__,
                               "override_wc_curve": rd["wc_curve"],
                               "override_density": rd["density"],
                               "override_fine_pct": rd["fine_pct"]})
        else:
            inp2 = inp
        res = design_mix(inp2)
        ref = ex["reference"]
        got = extract(res, ref)
        for k in ref:
            g, rv = got[k], ref[k]
            err = g - rv
            pct = 100.0 * err / rv if rv else 0.0
            tol = 0.005 if k == "wc_used" else max(0.03 * abs(rv), 15.0)
            ok = abs(err) <= tol if k != "wc_used" else abs(err) <= 0.005
            nd = 3 if k == "wc_used" else 1
            rows.append({"tier": tier, "example": name, "quantity": k,
                         "reference": round(rv, 3), "predicted": round(g, nd),
                         "error": round(err, nd), "error_pct": round(pct, 2),
                         "pass": ok})
    return rows


def main():
    all_rows = run(1) + run(2)
    out_csv = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                           "validation_results.csv")
    with open(out_csv, "w", newline="") as f:
        wtr = csv.DictWriter(f, fieldnames=list(all_rows[0]))
        wtr.writeheader()
        wtr.writerows(all_rows)

    for tier in (1, 2):
        rows = [r for r in all_rows if r["tier"] == tier]
        n_pass = sum(r["pass"] for r in rows)
        print(f"\n===== Tier {tier} "
              f"({'instructor chart readings injected' if tier == 1 else 'fully automated'}) "
              f"- {n_pass}/{len(rows)} PASS =====")
        print(f"{'ex':4} {'quantity':12} {'ref':>8} {'pred':>8} "
              f"{'err':>7} {'err%':>7}  ok")
        for r in rows:
            print(f"{r['example']:4} {r['quantity']:12} {r['reference']:>8} "
                  f"{r['predicted']:>8} {r['error']:>7} {r['error_pct']:>7}  "
                  f"{'PASS' if r['pass'] else '** FAIL **'}")
    print(f"\nSaved: {out_csv}")
    return all_rows


if __name__ == "__main__":
    main()
