"""
Digitize BRE Figure 5 ('Figure 3' in course supplementary materials):
estimated wet density of fully compacted concrete vs free-water content,
for combined aggregate relative density (SSD) 2.4-2.9.

Same clean-slice method as digitize_fig4_v2: sample vertical slices, keep
slices with exactly SIX curve strokes (the 6 density lines), assign
top->bottom to SG 2.9..2.4, robust linear fit per line.
Axes: x = free-water content 100-280 kg/m3 (gridlines every 20);
      y = wet density 2100-2700 kg/m3 (gridlines every 100).
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
SG_LABELS = [2.9, 2.8, 2.7, 2.6, 2.5, 2.4]   # top -> bottom


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
    im = Image.open(SRC / "Supplementary Materials_Page_3.tiff").convert("L")
    w, h = im.size
    # Figure 3 occupies the lower half of page 3; downsample 2x to save memory
    im = im.crop((int(0.10 * w), int(0.30 * h), int(0.92 * w), int(0.72 * h)))
    im = im.resize((im.size[0] // 2, im.size[1] // 2))
    panel = np.asarray(im)
    del im
    mask = panel < 190

    # horizontal gridlines are strong in this chart: 2700..2100 every 100
    hl_all = find_lines(mask, axis=1, min_frac=0.35)
    if len(hl_all) < 4:
        raise RuntimeError(f"h-grid failed: {hl_all}")
    hpos = np.array(hl_all, dtype=float)
    box_top = int(hpos[0])
    hgaps = np.diff(hpos)
    hunit = float(np.median(hgaps))
    # drop a leading frame line sitting at a partial gap above the 2700 line
    if len(hgaps) >= 2 and hgaps[0] < 0.75 * hunit:
        hpos = hpos[1:]
        hgaps = np.diff(hpos)
        hunit = float(np.median(hgaps))
    hidx = np.concatenate([[0], np.cumsum(np.round(hgaps / hunit))]).astype(int)
    if hidx[-1] != 6:
        raise RuntimeError(f"h-grid span != 6 units: {hl_all} idx={list(hidx)}")
    # index i (top->bottom) -> density 2700 - 100*i
    y_scale = np.polyfit(hpos, 2700.0 - 100.0 * hidx, 1)
    box_bot = int(hpos[-1])
    hl = [int(r) for r in hpos]

    # vertical gridlines (faint): detect within the box band, every 20 kg/m3.
    # The right-hand frame (280 kg/m3) is lighter than the interior lines, so
    # the stricter 0.55 threshold silently dropped it and produced an
    # eight-interval calibration. The 0.35 threshold retains the ten expected
    # lines from 100 through 280 while still excluding the table border above.
    vl = find_lines(mask[box_top + 5:box_bot - 5], axis=0, min_frac=0.35)
    merged = []
    for c in vl:
        if merged and c - merged[-1] < 20:
            merged[-1] = (merged[-1] + c) // 2
        else:
            merged.append(int(c))
    vl = merged
    print("vlines:", vl, "hlines:", hl)
    varr = np.array(vl, dtype=float)
    gaps = np.diff(varr)
    unit = float(np.median(gaps))
    idxs = np.concatenate([[0], np.cumsum(np.round(gaps / unit))]).astype(int)
    if idxs[-1] != 9:
        raise RuntimeError(
            f"x-grid span {idxs[-1]} != 9 (100..280): {vl}; inspect source crop"
        )
    x_scale = np.polyfit(varr, 100 + 20.0 * idxs, 1)
    print("x indices:", list(idxs))

    # erase grid, slice-sample
    work = mask.copy()
    for c in vl:
        work[:, max(0, c - 7):c + 7] = False
    for r in find_lines(mask, axis=1, min_frac=0.35):
        work[max(0, r - 7):r + 7, :] = False
    work[:box_top + 8, :] = False
    work[box_bot - 8:, :] = False
    work[:, :vl[0] + 8] = False
    work[:, vl[-1] - 8:] = False

    all_th = [t for x in range(vl[0] + 20, vl[-1] - 20, 25)
              for _, t in runs_in_col(work[:, x])]
    med = np.median(all_th)

    slices = {sg: [] for sg in SG_LABELS}
    n_ok = 0
    for x in range(vl[0] + 20, vl[-1] - 20, 6):
        rr = [r for r in runs_in_col(work[:, x]) if med * 0.45 <= r[1] <= med * 2.5]
        if len(rr) != 6:
            continue
        rr = sorted(rr, key=lambda z: z[0])
        wv = float(np.polyval(x_scale, x))
        n_ok += 1
        for sg, (yc, _) in zip(SG_LABELS, rr):
            slices[sg].append((wv, float(np.polyval(y_scale, yc))))

    out = {}
    for sg in SG_LABELS:
        pts = np.array(slices[sg])
        if len(pts) < 12:
            out[str(sg)] = None
            continue
        x_, y_ = pts[:, 0], pts[:, 1]
        ii, jj = np.triu_indices(len(x_), k=1)
        dx = x_[jj] - x_[ii]
        ok = np.abs(dx) > 1e-6
        b = float(np.median((y_[jj] - y_[ii])[ok] / dx[ok]))
        a = float(np.median(y_ - b * x_))
        resid = y_ - (a + b * x_)
        rm = np.sqrt((resid ** 2).mean())
        keep = np.abs(resid) <= max(1.5 * rm, 4.0)
        b, a = np.polyfit(x_[keep], y_[keep], 1)
        resid = y_[keep] - (a + b * x_[keep])
        out[str(sg)] = {"a": round(a, 2), "b": round(b, 4),
                        "n_slices": int(keep.sum()),
                        "w_range": [round(float(x_.min()), 1), round(float(x_.max()), 1)],
                        "rmse": round(float(np.sqrt((resid ** 2).mean())), 2)}
        print(sg, out[str(sg)])
    print("clean slices:", n_ok)

    with open(DATA_OUT / "fig5_wet_density_digitized.json", "w") as f:
        json.dump(out, f, indent=1)

    # validation vs instructor readings
    def density(sg, wv):
        import bisect
        sgs = [s for s in SG_LABELS if out[str(s)]]
        vals = {s: out[str(s)]["a"] + out[str(s)]["b"] * wv for s in sgs}
        sgs_sorted = sorted(sgs)
        if sg <= sgs_sorted[0]:
            return vals[sgs_sorted[0]]
        if sg >= sgs_sorted[-1]:
            return vals[sgs_sorted[-1]]
        for lo, hi in zip(sgs_sorted, sgs_sorted[1:]):
            if lo <= sg <= hi:
                t = (sg - lo) / (hi - lo)
                return vals[lo] + t * (vals[hi] - vals[lo])

    print("\n--- validation vs instructor readings ---")
    print("Ex1 SG2.65 W=151: pred", round(density(2.65, 151)), "instructor 2450")
    print("Ex2 SG2.5  W=160: pred", round(density(2.5, 160)), "instructor 2330")
    print("Ex3 SG2.65 W=215: pred", round(density(2.65, 215)), "instructor 2375")

    # QA overlay
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    fig, ax = plt.subplots(figsize=(9, 6))
    ax.imshow(panel, cmap="gray")
    xs_px = np.linspace(vl[0], vl[-1], 40)
    for sg in SG_LABELS:
        v = out[str(sg)]
        pts = np.array(slices[sg]) if slices[sg] else None
        if pts is not None and len(pts):
            xp = (pts[:, 0] - x_scale[1]) / x_scale[0]
            yp = (pts[:, 1] - y_scale[1]) / y_scale[0]
            ax.plot(xp, yp, '.', ms=2, color="red")
        if v:
            wline = np.polyval(x_scale, xs_px)
            dline = v["a"] + v["b"] * wline
            ypx = (dline - y_scale[1]) / y_scale[0]
            ax.plot(xs_px, ypx, '-', lw=0.8, color="lime")
    ax.axis("off")
    fig.savefig(QA_OUT / "qa2_fig5_density.png", dpi=90, bbox_inches="tight")
    plt.close(fig)


if __name__ == "__main__":
    main()
