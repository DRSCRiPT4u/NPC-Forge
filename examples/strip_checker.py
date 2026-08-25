"""Remove a baked-in light checkerboard background (AI image exports) -> real alpha.
Uses the checker STRUCTURE: estimates the two tones, the cell size and phase from the border, and only
kills pixels that match the expected tone at their position. Enclosed background holes (between limbs)
are recognised because they contain both tones in the right places; uniform white details (flowers,
eyes) do not. Thin anti-aliased bridges are broken with an erode/dilate step so blades keep their highlights."""
import sys
from PIL import Image
import numpy as np
from scipy import ndimage

def runs(v):
    d = np.abs(np.diff(v.astype(int), axis=0)).sum(axis=1) > 12
    idx = np.where(d)[0]
    return idx

def strip(src, dst, tol=9, min_hole=1500):
    a = np.array(Image.open(src).convert('RGBA')).astype(int)
    rgb = a[:, :, :3]; H, W = rgb.shape[:2]
    border = np.concatenate([rgb[0], rgb[-1], rgb[:, 0], rgb[:, -1]])
    border = border[(border.max(axis=1) - border.min(axis=1)) <= 10]
    vals, counts = np.unique(border // 2 * 2, axis=0, return_counts=True)
    order = np.argsort(-counts); tA = vals[order[0]].mean()
    tB = next((vals[o].mean() for o in order[1:] if abs(vals[o].mean() - tA) > 3), tA - 8)
    lum = rgb.mean(axis=2)
    lowsat = (rgb.max(axis=2) - rgb.min(axis=2)) <= 12
    isA = lowsat & (np.abs(lum - tA) <= tol); isB = lowsat & (np.abs(lum - tB) <= tol)
    match = isA | isB
    core = ndimage.binary_erosion(match, iterations=1)          # break anti-aliased bridges into the art
    lab, n = ndimage.label(core)
    border_ids = set(np.unique(np.concatenate([lab[0], lab[-1], lab[:, 0], lab[:, -1]]))) - {0}
    keep = set(border_ids)
    for i in range(1, n + 1):
        if i in border_ids: continue
        comp = lab == i
        if comp.sum() < min_hole: continue
        fa, fb = isA[comp].mean(), isB[comp].mean()
        if fa > 0.15 and fb > 0.15: keep.add(i)                  # both checker tones -> enclosed background hole
    kill = np.isin(lab, list(keep))
    kill = ndimage.binary_dilation(kill, iterations=1) & match
    fringe = ndimage.binary_dilation(kill, iterations=1) & ~kill & lowsat & (lum >= 225)
    kill |= fringe
    a[kill] = 0
    Image.fromarray(a.astype(np.uint8), 'RGBA').save(dst)
    print(f'{src} -> {dst}: tones {tA:.0f}/{tB:.0f} removed {int(kill.sum())} px ({kill.mean()*100:.0f}%)')

if __name__ == '__main__':
    strip(sys.argv[1], sys.argv[2])
