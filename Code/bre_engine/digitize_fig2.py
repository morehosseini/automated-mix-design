"""
T0.1 — Digitize BRE Figure 2 ('Figure 2' in the course supplementary materials,
Supplementary Materials_Page_2.tiff): compressive strength vs free-water/cement
ratio, family of curves labelled at the w/c=0.5 'starting line'. The curve
count is detected from the scan rather than assumed; the current source scan
contains 9 printed curves.

Method: same clean-slice + robust-fit pipeline as digitize_fig3.py /
digitize_fig4_v2.py, adapted for a chart where curves DIVERGE at the left
edge (w/c=0.3) and CONVERGE at the right edge (w/c=0.9) — the reverse of
Figure 4 — so curves are seeded on the left and tracked rightward.

Because the family is (to first order) an Abrams-type exponential decay,
S(wc) = S0.5 * B ** (0.5 - wc), curves are parallel in ln(S)-vs-wc space.
Rather than fitting each curve independently, we pool all detected curves into
a single fixed-effects regression:
    ln(S) = intercept_k + slope * wc   (k = curve index)
solved by least squares, giving ONE chart-derived slope estimate for the
whole family using every digitized point (n ~ 900+), which is what feeds
back into the engine as `LN_B`.
"""
import json
from pathlib import Path

import numpy as np
from PIL import Image

Image.MAX_IMAGE_PIXELS = None
PROJECT_ROOT = Path(__file__).resolve().parents[2]
SRC = PROJECT_ROOT / "sources"
DATA_OUT = PROJECT_ROOT / "Code" / "bre_engine" / "data"
QA_OUT = PROJECT_ROOT / "Code" / "bre_engine" / "qa_overlays"
DATA_OUT.mkdir(parents=True, exist_ok=True)
QA_OUT.mkdir(parents=True, exist_ok=True)
# number of curves and their nominal labels (value at wc=0.5, top to bottom)
# are DETECTED from the scan (see main()), not hardcoded.


def find_lines(mask, axis, min_frac):
    frac = mask.mean(axis=axis)
    idx = np.where(frac > min_frac)[0]
    clusters = []
    if len(idx) == 0:
        return clusters
    start = prev = idx[0]
    for i in idx[1:]:
        if i - prev > 3:
            clusters.append((start + prev) // 2)
            start = i
        prev = i
    clusters.append((start + prev) // 2)
    return clusters


def runs_in_col(col):
    ys = np.where(col)[0]
    out = []
    if len(ys) == 0:
        return out
    s = p = ys[0]
    for y in ys[1:]:
        if y - p > 2:
            out.append(((s + p) / 2.0, p - s + 1))
            s = y
        p = y
    out.append(((s + p) / 2.0, p - s + 1))
    return out


def main():
    im = Image.open(SRC / "Supplementary Materials_Page_2.tiff").convert("L")
    w, h = im.size
    # tight crop around the Figure 2 plot box (verified against fig2_tight_debug.png)
    im = im.crop((int(0.205 * w), int(0.245 * h), int(0.83 * w), int(0.775 * h)))
    im = im.resize((im.size[0] // 2, im.size[1] // 2))
    panel = np.asarray(im)
    del im
    mask = panel < 190

    # horizontal gridlines: 90..0 step 10 (10 lines)
    hl_all = find_lines(mask, axis=1, min_frac=0.35)
    if len(hl_all) < 6:
        raise RuntimeError(f"h-grid failed: {hl_all}")
    hpos = np.array(hl_all, dtype=float)
    hgaps = np.diff(hpos)
    hunit = float(np.median(hgaps))
    # drop spurious leading lines (e.g. a table border above the chart) whose
    # gap to the next line is far smaller than the regular grid spacing
    while len(hgaps) and hgaps[0] < 0.6 * hunit:
        hpos = hpos[1:]
        hgaps = np.diff(hpos)
        hunit = float(np.median(hgaps))
    hidx = np.concatenate([[0], np.cumsum(np.round(hgaps / hunit))]).astype(int)
    print("hlines:", hl_all, "idx:", list(hidx))
    if hidx[-1] < 6:
        raise RuntimeError(f"h-grid span too small: idx={list(hidx)}")
    # index i (top->bottom) -> value = top_value - 10*i ; top line should be 90
    top_val = 90.0
    y_scale = np.polyfit(hpos, top_val - 10.0 * hidx, 1)
    box_top, box_bot = int(hpos[0]), int(hpos[-1])

    # vertical gridlines: 0.3..0.9 step 0.1 (7 lines)
    vl_all = find_lines(mask[box_top + 5:box_bot - 5], axis=0, min_frac=0.35)
    merged = []
    for c in vl_all:
        if merged and c - merged[-1] < 15:
            merged[-1] = (merged[-1] + c) // 2
        else:
            merged.append(int(c))
    vl_all = merged
    print("vlines:", vl_all)
    varr = np.array(vl_all, dtype=float)
    gaps = np.diff(varr)
    unit = float(np.median(gaps))
    idxs = np.concatenate([[0], np.cumsum(np.round(gaps / unit))]).astype(int)
    print("v idx:", list(idxs))
    x_scale = np.polyfit(varr, 0.3 + 0.1 * idxs, 1)
    box_left, box_right = int(varr[0]), int(varr[-1])

    # sanity: the bold vertical "starting line" at wc=0.5 should coincide with
    # a real gridline (already included above), so no special handling needed.

    # erase gridlines/frame
    work = mask.copy()
    for c in vl_all:
        work[:, max(0, c - 6):c + 6] = False
    for r in hl_all:
        work[max(0, r - 6):r + 6, :] = False
    work[:box_top + 8, :] = False
    work[box_bot - 6:, :] = False
    work[:, :box_left + 8] = False
    work[:, box_right - 6:] = False
    # blank out the label textbox ("Starting line using data from Table 2" + arrow)
    # located near the top, roughly wc 0.38-0.62, value 78-90
    x0 = int(np.polyval([1 / x_scale[0], -x_scale[1] / x_scale[0]], 0.37))
    x1 = int(np.polyval([1 / x_scale[0], -x_scale[1] / x_scale[0]], 0.63))
    y0 = int(np.polyval([1 / y_scale[0], -y_scale[1] / y_scale[0]], 90))
    y1 = int(np.polyval([1 / y_scale[0], -y_scale[1] / y_scale[0]], 76))
    work[min(y0, y1):max(y0, y1), min(x0, x1):max(x0, x1)] = False

    all_th = [t for x in range(box_left + 20, box_right - 20, 20)
              for _, t in runs_in_col(work[:, x])]
    med = np.median(all_th)
    print("stroke thickness median:", med)

    # detect curve count as the MODE of stroke counts near the left edge
    # (max separation region), rather than hardcoding it
    counts = []
    for x in range(box_left + 12, box_left + 200, 2):
        rr = [r for r in runs_in_col(work[:, x]) if med * 0.45 <= r[1] <= med * 2.5]
        counts.append(len(rr))
    vals, freq = np.unique(counts, return_counts=True)
    N_CURVES = int(vals[np.argmax(freq)])
    print(f"detected N_CURVES = {N_CURVES} (mode over {len(counts)} columns; "
          f"distribution {dict(zip(vals.tolist(), freq.tolist()))})")

    # seed N_CURVES curves at the LEFT edge (max separation), track rightward
    seed_x = None
    for x in range(box_left + 12, box_left + 200):
        rr = [r for r in runs_in_col(work[:, x]) if med * 0.45 <= r[1] <= med * 2.5]
        if len(rr) == N_CURVES:
            seed_x = x
            seed_pts = sorted(rr, key=lambda z: z[0])
            break
    if seed_x is None:
        raise RuntimeError(f"could not seed {N_CURVES} curves near left edge")
    print("seeded at x =", seed_x)
    tracks = {i: [(seed_x, y)] for i, (y, _) in enumerate(seed_pts)}

    for x in range(seed_x + 1, box_right - 12):
        rr = [r for r in runs_in_col(work[:, x]) if med * 0.45 <= r[1] <= med * 2.5]
        if not rr:
            continue
        for i in range(N_CURVES):
            tr = tracks[i]
            pts = tr[-6:]
            if len(pts) >= 2:
                fit = np.polyfit([p[0] for p in pts], [p[1] for p in pts], 1)
                pred = np.polyval(fit, x)
            else:
                pred = pts[-1][1]
            cand = [r for r in rr if abs(r[0] - pred) < med * 2.5]
            if cand:
                best = min(cand, key=lambda z: abs(z[0] - pred))
                tr.append((x, best[0]))

    # convert to data space; fixed-effects (pooled) regression: ln(S) = c_k + slope*wc
    rows_x, rows_y, rows_k = [], [], []
    per_curve = {}
    for i in range(N_CURVES):
        pts = tracks[i]
        wc = np.polyval(x_scale, np.array([p[0] for p in pts]))
        s = np.polyval(y_scale, np.array([p[1] for p in pts]))
        keep = (wc >= 0.31) & (wc <= 0.88) & (s > 1.0)
        wc, s = wc[keep], s[keep]
        per_curve[i] = {"n_raw": int(len(wc)), "s_at_0.5": None}
        if len(wc) < 15:
            continue
        rows_x.append(wc); rows_y.append(np.log(s)); rows_k.append(np.full(len(wc), i))
    X = np.concatenate(rows_x); Y = np.concatenate(rows_y); K = np.concatenate(rows_k)

    # design matrix: one dummy intercept per curve + shared slope on wc
    D = np.zeros((len(X), N_CURVES + 1))
    for i in range(N_CURVES):
        D[K == i, i] = 1.0
    D[:, -1] = X
    coef, *_ = np.linalg.lstsq(D, Y, rcond=None)
    intercepts, slope = coef[:-1], coef[-1]
    ln_b_chart = -slope   # since ln(S) = c - LN_B*wc  =>  slope = -LN_B

    resid = Y - D @ coef
    rmse_ln = float(np.sqrt((resid ** 2).mean()))

    for i in range(N_CURVES):
        c_i = intercepts[i]
        per_curve[i]["s_at_0.5"] = round(float(np.exp(c_i + slope * 0.5)), 2)
        m = K == i
        per_curve[i]["n_fit"] = int(m.sum())
        per_curve[i]["rmse_ln"] = round(float(np.sqrt((resid[m] ** 2).mean())), 4)

    print("\nPer-curve summary (digitized value at wc=0.5):")
    for i in range(N_CURVES):
        print(f"  curve {i}: digitized@0.5 {per_curve[i]['s_at_0.5']:>6}  "
              f"n={per_curve[i]['n_fit']}  rmse_ln={per_curve[i]['rmse_ln']}")
    print(f"\nPooled fixed-effects fit: slope = {slope:.4f}  ->  LN_B (chart) = "
          f"{ln_b_chart:.4f}  (B = {np.exp(ln_b_chart):.2f})")
    print(f"Pooled RMSE (ln S) = {rmse_ln:.4f}  n_points = {len(X)}")

    out = {
        "ln_b_chart": round(float(ln_b_chart), 4),
        "b_chart": round(float(np.exp(ln_b_chart)), 3),
        "pooled_rmse_ln": round(rmse_ln, 4),
        "n_points": int(len(X)),
        "per_curve": {str(i): per_curve[i] for i in range(N_CURVES)},
        "model": "ln(S) = intercept_k + slope * wc, pooled fixed-effects OLS "
                 "across all detected digitized curves; LN_B = -slope",
        "wc_domain": [0.3, 0.9],
    }
    with open(DATA_OUT / "fig2_strength_wc_digitized.json", "w") as f:
        json.dump(out, f, indent=1)

    # validation vs the three instructor readings (Table 2 S0.5, target f_m)
    def wc_pred(s05, fm):
        return 0.5 + np.log(s05 / fm) / ln_b_chart

    print("\n--- validation vs instructor readings ---")
    checks = [("Ex1 S05=49 fm=45", 49, 45, 0.53),
              ("Ex2 S05=42 fm=35", 42, 35, 0.55),
              ("Ex3 S05=42 fm=30", 42, 30, 0.63)]
    max_dev = 0.0
    for name, s05, fm, ref in checks:
        pred = wc_pred(s05, fm)
        dev = abs(pred - ref)
        max_dev = max(max_dev, dev)
        print(f"  {name}: pred={pred:.3f}  instructor={ref}  dev={dev:.3f}")
    print(f"  max deviation = {max_dev:.3f} (tolerance 0.02)")

    # QA overlay
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    fig, ax = plt.subplots(figsize=(7, 9))
    ax.imshow(panel, cmap="gray")
    for i in range(N_CURVES):
        pts = np.array(tracks[i])
        ax.plot(pts[:, 0], pts[:, 1], '.', ms=1.5, color="red")
        if per_curve[i]["s_at_0.5"] is None:
            continue
        # clip the fitted line overlay to this curve's own observed x-range
        xs_px = np.linspace(pts[:, 0].min(), pts[:, 0].max(), 40)
        wc_line = np.polyval(x_scale, xs_px)
        c_i = intercepts[i]
        s_line = np.exp(c_i + slope * wc_line)
        y_px = (s_line - y_scale[1]) / y_scale[0]
        ax.plot(xs_px, y_px, '-', lw=0.7, color="lime")
    ax.set_ylim(panel.shape[0], 0)
    ax.set_xlim(0, panel.shape[1])
    ax.axis("off")
    ax.set_title("Figure 2 digitization (red=tracked points, green=pooled fit)")
    fig.savefig(QA_OUT / "qa2_fig2_strength.png", dpi=100, bbox_inches="tight")
    plt.close(fig)
    print("\nsaved JSON + overlay.")


if __name__ == "__main__":
    main()
