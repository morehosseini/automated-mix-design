"""
Digitize the BRE 'proportion of fine aggregate' design chart (Figure 6 of
BRE 'Design of Normal Concrete Mixes', 2nd ed. 1997; reproduced as 'Figure 4'
in the course supplementary materials) from the high-resolution scans.

Method (v2 - clean-slice sampling):
 1. Crop each of the 12 panels (3 max-agg sizes x 4 slump bands) using
    manually verified bounding boxes.
 2. Calibrate px->data: y from the plot frame extent (80% top, 10% bottom,
    verified against detected interior gridlines); x from the left frame
    (w/c = 0.2) and interior gridline spacing (0.2 per gridline).
 3. Erase gridlines, then sample ~45 vertical slices per panel. A slice is
    accepted only when exactly FIVE curve strokes of plausible thickness are
    found; slices crossing label text are thereby rejected automatically.
 4. The five strokes in each accepted slice are assigned top->bottom to the
    15/40/60/80/100 (% passing 600 um) curves - the curves never cross.
 5. Robust linear fit per curve: pct = a + b * (w/c), with a second pass
    removing >2*RMSE outliers. Overlay QA images are produced for audit.
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

PAGES = {
    10: "Supplementary Materials_Page_4.tiff",
    20: "Supplementary Materials_Page_4.tiff",
    40: "Supplementary Materials_Page_5.tiff",
}
SLUMP_BANDS = ["0-10", "10-30", "30-60", "60-180"]
# Panel bounding boxes as page fractions (x0, x1); '_y' = (y0, y1) per row.
PANELS = {
    10: {"0-10": (0.200, 0.362), "10-30": (0.376, 0.520),
         "30-60": (0.524, 0.670), "60-180": (0.677, 0.823),
         "_y": (0.132, 0.348)},
    20: {"0-10": (0.216, 0.370), "10-30": (0.374, 0.514),
         "30-60": (0.521, 0.663), "60-180": (0.671, 0.811),
         "_y": (0.435, 0.645)},
    40: {"0-10": (0.208, 0.375), "10-30": (0.385, 0.529),
         "30-60": (0.536, 0.679), "60-180": (0.688, 0.832),
         "_y": (0.145, 0.360)},
}
CURVE_LABELS = [15, 40, 60, 80, 100]


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


def digitize_panel(gray, tag=""):
    mask = gray < 128

    # ---- vertical lines (frames + gridlines) ----
    vl = find_lines(mask, axis=0, min_frac=0.25)
    # merge double-detected lines closer than 40 px
    merged = []
    for c in vl:
        if merged and c - merged[-1] < 40:
            merged[-1] = (merged[-1] + c) // 2
        else:
            merged.append(int(c))
    vl = merged
    if len(vl) < 2:
        raise RuntimeError(f"{tag}: vertical line detection failed {vl}")

    # box vertical extent: primary = agreement of the two frame columns;
    # fallback = the vline column with the longest run (broken frames)
    tops, bots = [], []
    for c in (vl[0], vl[-1]):
        col = mask[:, max(0, c - 3):c + 3].max(axis=1)
        ys = np.where(col)[0]
        if len(ys):
            tops.append(ys[0]); bots.append(ys[-1])
    box_top, box_bot = int(np.max(tops)), int(np.min(bots))
    if box_bot - box_top < mask.shape[0] * 0.4:
        best_ext = None
        for c in vl:
            col = mask[:, max(0, c - 3):c + 3].max(axis=1)
            ys = np.where(col)[0]
            if len(ys) and (best_ext is None or ys[-1] - ys[0] > best_ext[1] - best_ext[0]):
                best_ext = (ys[0], ys[-1])
        box_top, box_bot = int(best_ext[0]), int(best_ext[1])
        print(f"  note {tag}: box extent from longest frame run (fallback)")
    if box_bot - box_top < mask.shape[0] * 0.4:
        raise RuntimeError(f"{tag}: implausible box extent {box_top}-{box_bot}")

    # ---- y calibration: frame extents (top=80, bottom=10), then snap the
    # intercept by the median deviation of interior gridlines from decades ----
    y_scale = np.polyfit([box_top, box_bot], [80.0, 10.0], 1)
    hl = find_lines(mask[:, vl[0] + 12: vl[-1] - 12], axis=1, min_frac=0.45)
    hl = [r for r in hl if box_top + 40 < r < box_bot - 40]
    if len(hl) >= 2:
        devs = []
        for r in hl:
            v = np.polyval(y_scale, r)
            devs.append(v - round(v / 10) * 10)
        off = float(np.median(devs))
        if 0.5 < abs(off) <= 6:
            y_scale[1] -= off
            print(f"  note {tag}: y intercept snapped by {round(-off, 2)} (gridline decades)")

    # ---- x calibration: left frame = 0.2; gridlines 0.2 apart ----
    varr = np.array(vl, dtype=float)
    gaps = np.diff(varr)
    unit = float(np.median(gaps)) if len(gaps) >= 2 else (box_bot - box_top) / 7.0
    # drop right frame if it sits at a partial gap
    if len(gaps) >= 2 and (gaps[-1] < 0.75 * unit or
                           abs(gaps[-1] / unit - np.round(gaps[-1] / unit)) > 0.25):
        varr = varr[:-1]
        gaps = np.diff(varr)
        unit = float(np.median(gaps)) if len(gaps) >= 2 else (box_bot - box_top) / 7.0
    if len(varr) < 2:
        raise RuntimeError(f"{tag}: not enough x gridlines {vl}")
    idxs = np.concatenate([[0], np.cumsum(np.round(gaps / unit))]).astype(int)
    if idxs[-1] > 4 or idxs[-1] < 1:
        raise RuntimeError(f"{tag}: x-grid span implausible {vl} idx={list(idxs)}")
    x_scale = np.polyfit(varr, 0.2 + 0.2 * idxs, 1)

    # ---- erase gridlines/frames, keep curves ----
    work = mask.copy()
    for c in vl:
        work[:, max(0, c - 12):c + 12] = False
    for r in hl:
        work[max(0, r - 12):r + 12, :] = False
    work[:box_top + 14, :] = False
    work[box_bot - 14:, :] = False
    work[:, :int(varr[0]) + 14] = False
    work[:, int(vl[-1]) - 14:] = False

    # ---- stroke thickness statistics ----
    all_th = [t for x in range(int(varr[0]) + 20, int(vl[-1]) - 20, 25)
              for _, t in runs_in_col(work[:, x])]
    med = np.median(all_th)

    # ---- clean-slice sampling ----
    slices = {lab: [] for lab in CURVE_LABELS}
    n_ok = 0
    for x in range(int(varr[0]) + 20, int(vl[-1]) - 20, 6):
        rr = [r for r in runs_in_col(work[:, x]) if med * 0.45 <= r[1] <= med * 2.5]
        if len(rr) != 5:
            continue
        rr = sorted(rr, key=lambda z: z[0])          # top -> bottom
        wc = float(np.polyval(x_scale, x))
        n_ok += 1
        for lab, (yc, _) in zip(CURVE_LABELS, rr):
            slices[lab].append((wc, float(np.polyval(y_scale, yc))))

    curves = {}
    for lab in CURVE_LABELS:
        pts = np.array(slices[lab])
        if len(pts) < 12:
            curves[lab] = None
            continue
        # Theil-Sen: robust to label-stroke outliers (breakdown ~29%)
        x, y = pts[:, 0], pts[:, 1]
        ii, jj = np.triu_indices(len(x), k=1)
        dx = x[jj] - x[ii]
        ok = np.abs(dx) > 1e-6
        b = float(np.median((y[jj] - y[ii])[ok] / dx[ok]))
        a = float(np.median(y - b * x))
        resid = y - (a + b * x)
        rm = np.sqrt((resid ** 2).mean())
        keep = np.abs(resid) <= max(1.5 * rm, 0.4)
        b, a = np.polyfit(x[keep], y[keep], 1)
        resid = y[keep] - (a + b * x[keep])
        curves[lab] = {
            "a": round(float(a), 3), "b": round(float(b), 3),
            "n_slices": int(keep.sum()),
            "wc_range": [round(float(pts[:, 0].min()), 3), round(float(pts[:, 0].max()), 3)],
            "rmse": round(float(np.sqrt((resid ** 2).mean())), 3),
        }
    curves["_cal"] = {
        "x_scale": [float(v) for v in x_scale],
        "y_scale": [float(v) for v in y_scale],
        "n_clean_slices": n_ok,
        "points": {str(k): [[round(w, 4), round(p, 3)] for w, p in v] for k, v in slices.items()},
    }
    return curves


def main():
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    out = {}
    for size, fname in PAGES.items():
        im = Image.open(SRC / fname).convert("L")
        w, h = im.size
        page = np.asarray(im)
        yf0, yf1 = PANELS[size]["_y"]
        out[size] = {}
        for band in SLUMP_BANDS:
            xf0, xf1 = PANELS[size][band]
            px = int(0.004 * w)
            panel = page[int(yf0 * h):int(yf1 * h),
                         max(0, int(xf0 * w) - px):min(w, int(xf1 * w) + px)]
            tag = f"{size}mm {band}"
            res = digitize_panel(panel, tag)
            out[size][band] = res
            show = {k: (v["a"], v["b"], v["rmse"], v["n_slices"]) if v else None
                    for k, v in res.items() if k != "_cal"}
            print(tag, show)

            cal = res["_cal"]
            fig, ax = plt.subplots(figsize=(6, 7))
            ax.imshow(panel, cmap="gray")
            xs_px = np.linspace(0, panel.shape[1] - 1, 50)
            for lab in CURVE_LABELS:
                pts = np.array(cal["points"][str(lab)]) if cal["points"][str(lab)] else None
                v = res[lab]
                if pts is not None and len(pts):
                    xp = (pts[:, 0] - cal["x_scale"][1]) / cal["x_scale"][0]
                    yp = (pts[:, 1] - cal["y_scale"][1]) / cal["y_scale"][0]
                    ax.plot(xp, yp, '.', ms=2, color="red")
                if v:
                    wc_line = np.polyval(cal["x_scale"], xs_px)
                    pct_line = v["a"] + v["b"] * wc_line
                    ypx = (pct_line - cal["y_scale"][1]) / cal["y_scale"][0]
                    ax.plot(xs_px, ypx, '-', lw=0.8, color="lime")
            ax.set_title(tag)
            ax.set_ylim(panel.shape[0], 0)
            ax.axis("off")
            fig.savefig(QA_OUT / f"qa2_{size}mm_{band}.png", dpi=90, bbox_inches="tight")
            plt.close(fig)

    with open(DATA_OUT / "fig6_fine_fraction_digitized.json", "w") as f:
        json.dump(out, f, indent=1)

    # validation against instructor chart readings in worked examples
    def interp(size, band, wc, passing):
        cs = out[size][band]
        labs = [l for l in CURVE_LABELS if cs[l]]
        vals = {l: cs[l]["a"] + cs[l]["b"] * wc for l in labs}
        if passing <= labs[0]:
            return vals[labs[0]]
        if passing >= labs[-1]:
            return vals[labs[-1]]
        for lo, hi in zip(labs, labs[1:]):
            if lo <= passing <= hi:
                t = (passing - lo) / (hi - lo)
                return vals[lo] + t * (vals[hi] - vals[lo])

    print("\n--- validation vs instructor readings ---")
    print("Ex1 40mm 10-30 wc0.50 70%: pred", round(interp(40, "10-30", 0.50, 70), 1), "instructor 22")
    print("Ex2 40mm 30-60 wc0.50 90%: pred", round(interp(40, "30-60", 0.50, 90), 1), "instructor 22")
    print("Ex3 20mm 60-180 wc0.45 50%: pred", round(interp(20, "60-180", 0.45, 50), 1), "instructor 40")


if __name__ == "__main__":
    main()
