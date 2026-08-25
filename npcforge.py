#!/usr/bin/env python
"""NpcForge - turn ONE character PNG into an animated Mapleonim NPC and ship it to every tree.

    python npcforge.py animate <regions.json> [--out DIR]          frames + preview gif/sheet
    python npcforge.py build   <regions.json> --id ID [--scale S]  frames -> <id>.img (+ validate)
    python npcforge.py deploy  <regions.json> --id ID --name NAME [--commit] [--dry-run]
    python npcforge.py all     <regions.json> --id ID --name NAME [--scale S] [--commit]
    python npcforge.py free-id [START]                            first free NPC ids from START
    python npcforge.py mirror-vps                                 push the committed NPC files to vps
    python npcforge.py gui     [image.png | regions.json]         region picker + live preview

regions.json (written by the GUI, or by hand):
{
  "image": "CL.png",                       # relative to the json, or absolute
  "delay": 120, "stand_frames": 10, "speak_frames": 8,
  "sway":  [{"box": [x0,y0,x1,y1], "root": "bottom", "amp": 22, "wave": 1.6, "lift": 0.125}],
  "wag":   [{"box": [x0,y0,x1,y1], "pivot": [x,y], "angles": [0, 6], "phase": 60,
             "behind": true, "overlap": 40, "speak_angles": [0, 8], "speak_speed": 2}],
  "mouth": {"box": [x0,y0,x1,y1], "cell": 10},
  "scale": 0.13
}
Everything is optional except "image"; empty lists mean "no such motion".
"""
import argparse, base64, io, json, math, os, re, shutil, subprocess, sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter
import numpy as np

# next to the .exe when frozen (PyInstaller), next to this file otherwise - theme/, examples/, npcforge.json live there
HERE = Path(sys.executable).resolve().parent if getattr(sys, 'frozen', False) else Path(__file__).resolve().parent
PATHS = {'wzforge': '', 'img_client': '', 'wz_client': '', 'server_wz': '', 'backup_dir': str(HERE / 'backup')}
if (HERE / 'npcforge.json').exists():
    PATHS.update(json.loads((HERE / 'npcforge.json').read_text(encoding='utf-8')))
HAVE_WZFORGE = bool(PATHS.get('wzforge')) and Path(PATHS['wzforge']).exists()
MOUTH_SEQ = ['closed', 'open1', 'open2', 'open1', 'closed', 'open2', 'open1', 'closed']


# ----------------------------------------------------------------------------- config
def load_cfg(path):
    path = Path(path).resolve()
    cfg = json.loads(path.read_text(encoding='utf-8'))
    img = Path(cfg['image'])
    if not img.is_absolute():
        img = path.parent / img
    cfg['_image'] = img
    cfg['_dir'] = path.parent
    cfg['_name'] = path.stem
    cfg.setdefault('delay', 120); cfg.setdefault('stand_frames', 10); cfg.setdefault('speak_frames', 8)
    cfg.setdefault('sway', []); cfg.setdefault('wag', []); cfg.setdefault('mouth', None); cfg.setdefault('blink', None)
    return cfg


def out_dir(cfg, override=None):
    d = Path(override) if override else cfg['_dir'] / f'{cfg["_name"]}_out'
    d.mkdir(parents=True, exist_ok=True)
    return d


# ----------------------------------------------------------------------------- animation engine
class Rig:
    """Splits the source image into a body layer + moving layers from the region boxes."""

    def __init__(self, cfg):
        self.cfg = cfg
        self.im = Image.open(cfg['_image']).convert('RGBA')
        self.W, self.H = self.im.size
        self.arr = np.array(self.im)
        self.solid = self.arr[:, :, 3] > 0
        self.ys, self.xs = np.mgrid[0:self.H, 0:self.W]
        body = self.solid.copy()

        self.sways = []
        for s in cfg['sway']:
            m = self._region_mask(s)
            box = self._mask_box(m) if s.get('poly') else self._clip(s['box'])
            self.sways.append({'mask': m, 'box': box, 'root': s.get('root', 'bottom'),
                               'amp': float(s.get('amp', 20)), 'wave': float(s.get('wave', 1.6)),
                               'lift': float(s.get('lift', 0.125))})
            body &= ~m

        self.wags = []
        cut = np.zeros_like(self.solid)
        for w in cfg['wag']:
            core = self._region_mask(w)
            box = self._mask_box(core)
            ov = int(w.get('overlap', 40))
            layer = self._region_mask(w, grow=ov) if ov else core
            for s in self.sways:                      # a sway region never travels with a limb
                layer &= ~s['mask']
            cut |= core
            self.wags.append({'mask': layer, 'pivot': tuple(w['pivot']), 'angles': list(w.get('angles', [0, 6])),
                              'phase': math.radians(float(w.get('phase', 60))), 'behind': bool(w.get('behind', True)),
                              'speak_angles': list(w.get('speak_angles', w.get('angles', [0, 6]))),
                              'speak_speed': float(w.get('speak_speed', 2)),
                              'keyframes': w.get('keyframes'), 'speak_keyframes': w.get('speak_keyframes'),
                              'parent': w.get('parent'), 'clip_below': w.get('clip_below'), 'box': box, 'core': core,
                              'extend': w.get('extend')})
            body &= ~core
        for w in self.wags:                            # a child limb (blade in a hand) is not part of its parent's layer
            if w['parent'] is not None:
                self.wags[int(w['parent'])]['mask'] &= ~w['core']
        for w in self.wags:                            # the cut edge: core pixels touching the rest of the drawing
            edge = w['core'] & self._grow(self.solid & ~w['core'], 1)
            w['edge'] = Image.fromarray(edge.astype(np.uint8) * 255, 'L')

        # flip regions: drawn mirrored (about their own centre) during given frames - a head turning to look back
        self.flips = []
        for fl in cfg.get('flip') or []:
            m = self._region_mask(fl)
            if not m.any(): continue
            x0, y0, x1, y1 = self._mask_box(m)
            normal = Image.fromarray(np.where(m[:, :, None], self.arr, 0).astype(np.uint8), 'RGBA')
            mirrored = Image.new('RGBA', (self.W, self.H), (0, 0, 0, 0))
            mirrored.paste(normal.crop((x0, y0, x1, y1)).transpose(Image.FLIP_LEFT_RIGHT), (x0, y0))
            edge = m & self._grow(self.solid & ~m, 1)
            em = Image.new('L', (self.W, self.H), 0)
            em.paste(Image.fromarray(edge.astype(np.uint8) * 255, 'L').crop((x0, y0, x1, y1)).transpose(Image.FLIP_LEFT_RIGHT), (x0, y0))
            self.flips.append({'normal': normal, 'mirrored': mirrored, 'frames': fl.get('frames') or [], 'speak': bool(fl.get('speak', True)),
                               'edge_mirrored': np.array(em) > 0})
            body &= ~m; cut |= m

        self.body_arr = np.zeros_like(self.arr); self.body_arr[body] = self.arr[body]
        if cfg.get('fill_body', True) and cut.any():
            self._fill_holes(body, cut)
        for s in self.sways:
            self._fill_under_sway(s)
        self.body = Image.fromarray(self.body_arr, 'RGBA')
        self.layers_sway = [Image.fromarray(np.where(s['mask'][:, :, None], self.arr, 0).astype(np.uint8), 'RGBA') for s in self.sways]
        self.layers_wag = [Image.fromarray(np.where(w['mask'][:, :, None], self.arr, 0).astype(np.uint8), 'RGBA') for w in self.wags]
        self.layers_wag_ext = [self._extend_limb(i) for i in range(len(self.wags))]
        self.mouth_owner = None
        self.mouths = self._mouth_variants(cfg['mouth']) if cfg['mouth'] else {'closed': self.body}
        self.blink_layer = self._blink_layer(cfg['blink']) if cfg.get('blink') else None

    def _blink_layer(self, b):
        """Closed-eyes overlay: the eye box filled with the surrounding face colour plus a thin dark lid line."""
        x0, y0, x1, y1 = self._clip(b['box'])
        ring = self._inbox(self._clip([x0 - 8, y0 - 8, x1 + 8, y1 + 8])) & ~self._inbox([x0, y0, x1, y1]) & self.solid
        face = tuple(int(v) for v in self._mode(self.arr[ring])) if ring.any() else (255, 230, 150, 255)
        inside = self.arr[y0:y1, x0:x1].reshape(-1, 4); inside = inside[inside[:, 3] > 0]
        lum = inside[:, :3].mean(axis=1)
        far = inside[lum < lum.mean() - 40]                       # the eye pixels: clearly darker than the skin
        dark = tuple(int(v) for v in np.median(far, axis=0)) if len(far) else (30, 30, 30, 255)
        dark = dark[:3] + (255,)
        layer = Image.new('RGBA', (self.W, self.H), (0, 0, 0, 0)); d = ImageDraw.Draw(layer)
        d.rectangle((x0, y0, x1 - 1, y1 - 1), fill=face)
        th = max(2, int(b.get('lid', (y1 - y0) // 5)))
        ly = y0 + int((y1 - y0) * 0.6)
        d.rectangle((x0 + 2, ly, x1 - 3, ly + th - 1), fill=dark)
        return layer

    # -- helpers
    def _region_mask(self, spec, grow=0):
        """Region = polygon ("poly": [[x,y],...]) or box ("box": [x0,y0,x1,y1]); grow = dilate by N px."""
        mask = np.zeros((self.H, self.W), bool)
        if spec.get('box'):
            mask |= self._inbox(self._clip(spec['box']))
        polys = spec.get('poly') or []
        if polys and not isinstance(polys[0][0], (list, tuple)):
            polys = [polys]                                   # one polygon, or a list of polygons (union)
        for poly in polys:
            m = Image.new('L', (self.W, self.H), 0)
            ImageDraw.Draw(m).polygon([tuple(int(v) for v in p) for p in poly], fill=255)
            mask |= np.array(m) > 0
        if grow:
            mask = np.array(Image.fromarray(mask.astype(np.uint8) * 255).filter(ImageFilter.MaxFilter(2 * int(grow) + 1))) > 0
        return mask & self.solid

    def _mask_box(self, mask):
        ys = np.where(mask.any(axis=1))[0]; xs = np.where(mask.any(axis=0))[0]
        if not len(ys): return [0, 0, 1, 1]
        return [int(xs[0]), int(ys[0]), int(xs[-1]) + 1, int(ys[-1]) + 1]

    def _clone_fill(self, arr, target, source, patch=7, radius=40, stride=2):
        """Clone-stamp style inpainting (exemplar based): every missing pixel is filled from the centre of the
        best-matching known patch nearby, working inward from the edge of the hole. arr is modified in place.
        target = pixels to fill, source = pixels that may be copied from."""
        target = target.copy(); known = source.copy() & ~target
        r = patch // 2
        H, W = target.shape
        pad = np.pad(arr[:, :, :3].astype(np.int16), ((r, r), (r, r), (0, 0)), mode='edge')
        kpad = np.pad(known, r, mode='constant')
        win = np.lib.stride_tricks.sliding_window_view(pad, (patch, patch), axis=(0, 1))       # H,W,3,p,p
        kwin = np.lib.stride_tricks.sliding_window_view(kpad, (patch, patch))                  # H,W,p,p
        valid = np.array(Image.fromarray(known.astype(np.uint8) * 255).filter(ImageFilter.MinFilter(patch))) > 0  # full patch known
        for _ in range(4000):
            if not target.any(): break
            ring = target & (np.array(Image.fromarray(known.astype(np.uint8) * 255).filter(ImageFilter.MaxFilter(3))) > 0)
            if not ring.any(): break
            ys, xs = np.where(ring)
            for y, x in zip(ys, xs):
                y0, y1 = max(0, y - radius), min(H, y + radius + 1); x0, x1 = max(0, x - radius), min(W, x + radius + 1)
                cand = valid[y0:y1:stride, x0:x1:stride]
                cy, cx = np.where(cand)
                if not len(cy):
                    continue
                cy = cy * stride + y0; cx = cx * stride + x0
                tp = win[y, x].transpose(1, 2, 0); tk = kwin[y, x]                 # p,p,3 and p,p
                if not tk.any():
                    continue
                cps = win[cy, cx].transpose(0, 2, 3, 1)                             # n,p,p,3
                d = ((cps - tp) ** 2).sum(axis=3) * tk                              # n,p,p
                best = np.argmin(d.sum(axis=(1, 2)))
                arr[y, x, :3] = arr[cy[best], cx[best], :3]; arr[y, x, 3] = 255
                pad[y + r, x + r] = arr[y, x, :3]
                known[y, x] = True; kpad[y + r, x + r] = True; target[y, x] = False
            valid = np.array(Image.fromarray(known.astype(np.uint8) * 255).filter(ImageFilter.MinFilter(patch))) > 0
        return arr

    def _inpaint(self, arr, target, source, margin=28, method='shiftmap', source_radius=None):
        """Continue the drawing into `target` using only `source` pixels as material. OpenCV's SHIFTMAP
        (patch based, contrib module) when available - it behaves like an automatic clone stamp - else the
        built-in exemplar fill. arr (HxWx4 uint8) is modified in place."""
        if not target.any():
            return arr
        if source_radius:                                                        # only borrow from nearby pixels
            source = source & self._grow(target, source_radius)
        try:
            import cv2
            ys, xs = np.where(target)
            y0, y1 = max(0, ys.min() - margin), min(self.H, ys.max() + margin + 1)
            x0, x1 = max(0, xs.min() - margin), min(self.W, xs.max() + margin + 1)
            src = np.ascontiguousarray(arr[y0:y1, x0:x1, :3][:, :, ::-1])            # BGR for OpenCV
            valid = (source & ~target)[y0:y1, x0:x1]
            mask = np.where(valid, 255, 0).astype(np.uint8)                          # 0 = inpaint (target + everything else)
            dst = np.zeros_like(src)
            if method == 'telea':                                                # smooth bridge - for thin seams
                tmask = np.where(target[y0:y1, x0:x1], 255, 0).astype(np.uint8)
                dst = cv2.inpaint(src, tmask, 3, cv2.INPAINT_TELEA)
            else:
                cv2.xphoto.inpaint(src, mask, dst, cv2.xphoto.INPAINT_SHIFTMAP)
            t = target[y0:y1, x0:x1]
            sub = arr[y0:y1, x0:x1]
            sub[t, :3] = dst[t][:, ::-1]; sub[t, 3] = 255
            return arr
        except Exception as ex:                                                       # no cv2 / contrib -> own clone fill
            if not getattr(self, '_warned_cv2', False):
                print(f'(inpaint: OpenCV shiftmap unavailable - {type(ex).__name__}; using built-in clone fill)'); self._warned_cv2 = True
            return self._clone_fill(arr, target, source)

    def _extend_limb(self, i):
        """Clone-stamp the limb a few px past its cut line (into where the body was) so a rotated limb shows
        no straight edge at the joint. Used only while the limb is actually rotated (see compose)."""
        w = self.wags[i]
        ext = w.get('extend')                                    # opt-in, per limb or global: clone the limb past its cut
        ext = int(self.cfg.get('extend', 0) if ext is None else ext)
        if ext <= 0: return None
        tgt = self._grow(w['core'], ext) & self.solid & ~w['core']
        for j, o in enumerate(self.wags):
            if j != i: tgt &= ~o['core']
        for s in self.sways: tgt &= ~s['mask']
        if not tgt.any(): return None
        a = np.where(w['mask'][:, :, None], self.arr, 0).astype(np.uint8)
        self._inpaint(a, tgt, w['core'])
        return Image.fromarray(a, 'RGBA')

    def _grow(self, mask, n):
        return np.array(Image.fromarray(mask.astype(np.uint8) * 255).filter(ImageFilter.MaxFilter(2 * int(n) + 1))) > 0

    def _fill_holes(self, body, cut, radius=None, steps=120):
        radius = int(radius or self.cfg.get("fill_radius", 24))
        """A limb cut out of the body leaves a hole where the limb overlapped the torso. Fill the part of
        that hole that lies inside the closed body silhouette with the nearest body colours, so the body
        stays whole when the limb moves away (the limb is drawn on top, so at rest nothing changes)."""
        m = Image.fromarray(body.astype(np.uint8) * 255)
        closed = np.array(m.filter(ImageFilter.MaxFilter(2 * radius + 1)).filter(ImageFilter.MinFilter(2 * radius + 1))) > 0
        hole = closed & ~body & cut
        if not hole.any(): return
        self._inpaint(self.body_arr, hole, body, source_radius=16)  # continue the body drawing into the hole

    def _clip(self, b):
        x0, y0, x1, y1 = [int(round(v)) for v in b]
        return [max(0, min(x0, x1)), max(0, min(y0, y1)), min(self.W, max(x0, x1)), min(self.H, max(y0, y1))]

    def _inbox(self, b):
        return (self.xs >= b[0]) & (self.xs < b[2]) & (self.ys >= b[1]) & (self.ys < b[3])

    def _fill_under_sway(self, s):
        """Roots barely move, but a 1px shift would open pinholes where the sway layer covered the body:
        fill the body under the last rows of the sway region with the body colour just past the root."""
        x0, y0, x1, y1 = s['box']
        rows = 60
        for x in range(x0, x1):
            if s['root'] == 'bottom':
                src_rows = range(y1, min(self.H, y1 + 6)); fill_rows = range(max(y0, y1 - rows), y1)
            else:
                src_rows = range(max(0, y0 - 6), y0); fill_rows = range(y0, min(y1, y0 + rows))
            col = None
            for y in src_rows:
                if self.body_arr[y, x, 3] > 0:
                    col = self.body_arr[y, x]; break
            if col is None:
                continue
            for y in fill_rows:
                if s['mask'][y, x] and self.body_arr[y, x, 3] == 0:
                    self.body_arr[y, x] = col

    def _mouth_variants(self, m):
        box = self._clip(m['box']); cell = int(m.get('cell', 10))
        x0, y0, x1, y1 = box
        # the mouth lives on whichever layer holds its centre pixel (a tilting head is a limb, not the body)
        self.mouth_owner = None; base = self.body
        for i, w in enumerate(self.wags):
            if w['mask'][(y0 + y1) // 2, (x0 + x1) // 2]:
                self.mouth_owner = i; base = self.layers_wag[i]; break
        inside = self.arr[y0:y1, x0:x1].reshape(-1, 4)
        inside = inside[inside[:, 3] > 0]
        # background of the mouth area = the lighter majority inside the box (skin, or beard on a bearded face);
        # the mouth stroke = the clearly darker pixels inside it
        lum = inside[:, :3].astype(int).mean(axis=1) if len(inside) else np.zeros(0)
        light = inside[lum >= np.median(lum)] if len(inside) else inside
        face = tuple(int(v) for v in self._mode(light)) if len(light) else (255, 255, 255, 255)
        far = inside[lum < lum.mean() - 30] if len(inside) else inside
        mouth = tuple(int(v) for v in np.median(far, axis=0)) if len(far) else tuple(int(v * 0.5) for v in face[:3]) + (255,)
        mouth = mouth[:3] + (255,)
        inner = tuple(int(v * 0.35) for v in mouth[:3]) + (255,)
        bw, bh = x1 - x0, y1 - y0
        cell = max(3, min(cell, bh // 3))                 # never coarser than a third of the box height
        cx = (x0 + x1) // 2

        def variant(wfrac, hfrac):
            """Open mouth: rounded dark shape on the pixel grid, `wfrac` of the box width, `hfrac` of its height
            (may grow below the box - an open mouth is taller than a closed one). Top edge stays at the box top."""
            img = base.copy(); d = ImageDraw.Draw(img)
            d.rectangle((x0, y0, x1 - 1, y1 - 1), fill=face)
            w = max(4, int(round(bw * wfrac / cell))); h = max(3, int(round(bh * hfrac / cell)))
            gx0 = cx - (w * cell) // 2
            for r in range(h):
                for c in range(w):
                    edge = r == 0 or r == h - 1 or c == 0 or c == w - 1
                    corner = (r in (0, h - 1)) and (c in (0, w - 1))
                    if corner:
                        continue
                    px, py = gx0 + c * cell, y0 + r * cell
                    d.rectangle((px, py, px + cell - 1, py + cell - 1), fill=mouth if edge else inner)
            return img
        return {'closed': base, 'open1': variant(0.55, 1.0), 'open2': variant(0.75, 1.6)}

    @staticmethod
    def _mode(px):
        q = (px[:, :3] // 8).astype(np.int64)
        keys = q[:, 0] * 1_000_000 + q[:, 1] * 1000 + q[:, 2]
        vals, counts = np.unique(keys, return_counts=True)
        k = vals[np.argmax(counts)]
        sel = px[keys == k]
        return np.median(sel, axis=0).astype(int).tolist()[:3] + [255]

    # -- motion primitives
    def sway(self, i, layer, phase):
        """root bottom/top: rows shift sideways (hair, leaves). root left/right: columns shift up/down
        (headband tails, a scarf, a tail sticking out sideways)."""
        s = self.sways[i]; x0, y0, x1, y1 = s['box']
        src = np.array(layer); dst = np.zeros_like(src)
        if s['root'] in ('left', 'right'):
            L = max(1, x1 - x0)
            for x in range(x0, x1):
                t = (x - x0) / L if s['root'] == 'left' else (x1 - 1 - x) / L
                sy = int(round(s['amp'] * t * t * math.sin(phase + s['wave'] * t)))
                col = np.roll(src[:, x], sy, axis=0)
                if sy > 0: col[:sy] = 0
                elif sy < 0: col[sy:] = 0
                dst[:, x] = np.where(col[:, 3:4] > 0, col, dst[:, x])
            return Image.fromarray(dst, 'RGBA')
        L = max(1, y1 - y0)
        for y in range(y0, y1):
            t = (y1 - 1 - y) / L if s['root'] == 'bottom' else (y - y0) / L
            dx = s['amp'] * t * t * math.sin(phase + s['wave'] * t)
            dy = -s['lift'] * s['amp'] * t * t * (1 - math.cos(phase + s['wave'] * t))
            if s['root'] == 'top':
                dy = -dy
            sx, ty = int(round(dx)), y + int(round(dy))
            if 0 <= ty < self.H:
                row = np.roll(src[y], sx, axis=0)
                if sx > 0: row[:sx] = 0
                elif sx < 0: row[sx:] = 0
                dst[ty] = np.where(row[:, 3:4] > 0, row, dst[ty])
        return Image.fromarray(dst, 'RGBA')

    def wag(self, i, layer, angle):
        return layer.rotate(angle, resample=Image.NEAREST, center=self.wags[i]['pivot'])

    @staticmethod
    def keyframe_angle(keys, k, n):
        """keys = [[frame, angle], ...] sorted; smooth (cosine) interpolation, wraps around the loop."""
        keys = sorted(keys)
        if k <= keys[0][0]: prev, nxt = keys[-1], keys[0]; prev = [prev[0] - n, prev[1]]
        elif k >= keys[-1][0]: prev, nxt = keys[-1], [keys[0][0] + n, keys[0][1]]
        else:
            j = max(i for i, kf in enumerate(keys) if kf[0] <= k); prev, nxt = keys[j], keys[j + 1]
        span = max(1, nxt[0] - prev[0]); t = (k - prev[0]) / span
        return prev[1] + (nxt[1] - prev[1]) * 0.5 * (1 - math.cos(math.pi * t))

    def compose(self, phase, mouth='closed', speak=False, k=0, n=1, blink=False):
        f = Image.new('RGBA', (self.W, self.H), (0, 0, 0, 0))
        angles = []
        for w in self.wags:
            keys = w.get('speak_keyframes') if speak else w.get('keyframes')
            if keys:
                angles.append(self.keyframe_angle(keys, k, n))
            else:
                a0, a1 = w['speak_angles'] if speak else w['angles']
                sp = w['speak_speed'] if speak else 1
                t = 0.5 * (1 - math.cos(sp * phase + w['phase']))
                angles.append(a0 + (a1 - a0) * t)

        def rot_point(p, ang, c):                       # PIL's counter-clockwise rotation, screen coordinates
            a = math.radians(ang); dx, dy = p[0] - c[0], p[1] - c[1]
            return (c[0] + dx * math.cos(a) + dy * math.sin(a), c[1] - dx * math.sin(a) + dy * math.cos(a))

        def chain(i):                                    # ancestors root-first
            out = []; j = self.wags[i]['parent']
            while j is not None: out.insert(0, int(j)); j = self.wags[int(j)]['parent']
            return out

        limbs = []
        bands = np.zeros((self.H, self.W), bool)         # seam bands to heal in this frame
        for i, w in enumerate(self.wags):
            total = abs(angles[i]) + sum(abs(angles[p]) for p in chain(i))
            layer = self.layers_wag_ext[i] if (total > 5 and self.layers_wag_ext[i] is not None) else self.layers_wag[i]
            if self.mouth_owner == i and mouth != 'closed':
                layer = self.mouths.get(mouth, layer)
            edge = w['edge']
            pivot = w['pivot']
            for p in chain(i):                           # carry the child along with every ancestor's rotation
                pp = self.wags[p]['pivot']
                layer = layer.rotate(angles[p], resample=Image.NEAREST, center=pp)
                edge = edge.rotate(angles[p], resample=Image.NEAREST, center=pp)
                pivot = rot_point(pivot, angles[p], pp)
            layer = layer.rotate(angles[i], resample=Image.NEAREST, center=pivot)
            edge = edge.rotate(angles[i], resample=Image.NEAREST, center=pivot)
            if w['clip_below'] is not None:              # e.g. the ground line: a blade stuck in the floor
                arr = np.array(layer); arr[int(w['clip_below']):] = 0; layer = Image.fromarray(arr, 'RGBA')
            if total > 2:
                bands |= self._grow(np.array(edge) > 0, 2)
            limbs.append((w['behind'], layer))
        for behind, L in limbs:
            if behind: f.alpha_composite(L)
        f.alpha_composite(self.mouths.get(mouth, self.body) if self.mouth_owner is None else self.body)
        for fl in self.flips:
            on = fl['speak'] if speak else any(a <= k <= b for a, b in fl['frames'])
            f.alpha_composite(fl['mirrored'] if on else fl['normal'])
            if on: bands |= self._grow(fl['edge_mirrored'], 2)
        if blink and self.blink_layer is not None:
            f.alpha_composite(self.blink_layer)
        for behind, L in limbs:
            if not behind: f.alpha_composite(L)
        for i, L in enumerate(self.layers_sway):
            f.alpha_composite(self.sway(i, L, phase))
        if bands.any() and self.cfg.get('heal_seams', True):   # clone-stamp along the moved cut edges
            fa = np.array(f); opaque = fa[:, :, 3] > 0
            target = bands & opaque
            self._inpaint(fa, target, opaque & ~target, margin=16, method='telea')
            f = Image.fromarray(fa, 'RGBA')
        return f

    def _blink_frames(self, n, anim):
        b = self.cfg.get('blink')
        if not b: return set()
        if anim == 'speak':
            at = b.get('speak_at') or []                 # no blink while talking unless asked for
        else:
            at = b.get('at') or [n - 2]                  # default: one closed frame near the end of the loop
        return {int(x) % n for x in at}

    def stand(self):
        n = int(self.cfg['stand_frames']); bl = self._blink_frames(n, 'stand')
        return [self.compose(2 * math.pi * k / n, k=k, n=n, blink=k in bl) for k in range(n)]

    def speak(self):
        n = int(self.cfg['speak_frames']); bl = self._blink_frames(n, 'speak')
        seq = (MOUTH_SEQ * ((n + len(MOUTH_SEQ) - 1) // len(MOUTH_SEQ)))[:n] if self.cfg['mouth'] else ['closed'] * n
        return [self.compose(2 * math.pi * k / n, mouth=seq[k], speak=True, k=k, n=n, blink=k in bl) for k in range(n)]


def write_previews(frames_by_anim, out, delay, scale=0.3):
    for name, frames in frames_by_anim.items():
        W, H = frames[0].size
        sw, sh = max(1, int(W * scale)), max(1, int(H * scale))
        sm = []
        for f in frames:
            s = f.resize((sw, sh), Image.LANCZOS)
            bg = Image.new('RGBA', s.size, (40, 40, 40, 255)); bg.alpha_composite(s)
            sm.append(bg.convert('P', palette=Image.ADAPTIVE, colors=255))
        sm[0].save(out / f'{name}_preview.gif', save_all=True, append_images=sm[1:], duration=delay, loop=0)
        cols = min(len(frames), 10); rows = (len(frames) + cols - 1) // cols
        sheet = Image.new('RGBA', (sw * cols, sh * rows), (40, 40, 40, 255))
        for k, f in enumerate(frames):
            sheet.alpha_composite(f.resize((sw, sh), Image.LANCZOS), ((k % cols) * sw, (k // cols) * sh))
        sheet.save(out / f'{name}_sheet.png')


def cmd_animate(cfg, out=None, quiet=False):
    rig = Rig(cfg)
    out = out_dir(cfg, out)
    anims = {'stand': rig.stand(), 'speak': rig.speak()}
    for name, frames in anims.items():
        d = out / 'frames' / name
        if d.exists(): shutil.rmtree(d)
        d.mkdir(parents=True)
        for k, f in enumerate(frames):
            f.save(d / f'{k}.png')
    write_previews(anims, out, cfg['delay'])
    if not quiet:
        print(f'frames: stand {len(anims["stand"])}, speak {len(anims["speak"])} -> {out / "frames"}')
        print(f'preview: {out / "stand_preview.gif"}, {out / "speak_preview.gif"}, *_sheet.png')
    return out, anims


# ----------------------------------------------------------------------------- build (.img)
def wzforge(*args, check=True):
    exe = PATHS['wzforge']
    r = subprocess.run([exe, *args], capture_output=True, text=True)
    txt = (r.stdout or '') + (r.stderr or '')
    if check and r.returncode not in (0,):
        raise SystemExit(f'WzForge {args[0]} failed (exit {r.returncode}):\n{txt}')
    return txt


def cmd_build(cfg, npc_id, scale=None, out=None):
    out = out_dir(cfg, out)
    fdir = out / 'frames'
    if not (fdir / 'stand').exists():
        print('no frames yet - running animate first'); cmd_animate(cfg, out)
    scale = float(scale or cfg.get('scale', 0.13))
    delay = int(cfg['delay'])
    anims = {}
    for name in ('stand', 'speak'):
        d = fdir / name
        files = sorted(d.glob('*.png'), key=lambda p: int(p.stem)) if d.exists() else []
        if files: anims[name] = [Image.open(p).convert('RGBA') for p in files]
    W, H = anims['stand'][0].size
    sw, sh = max(1, round(W * scale)), max(1, round(H * scale))
    small = {a: [f.resize((sw, sh), Image.LANCZOS) for f in fs] for a, fs in anims.items()}
    alpha = np.zeros((sh, sw), bool)
    for fs in small.values():
        for f in fs: alpha |= np.array(f)[:, :, 3] > 8
    rows = np.where(alpha.any(axis=1))[0]; cols = np.where(alpha.any(axis=0))[0]
    x0, x1, y0, y1 = int(cols[0]), int(cols[-1]) + 1, int(rows[0]), int(rows[-1]) + 1
    cw, ch = x1 - x0, y1 - y0
    a0 = np.array(small['stand'][0])[:, :, 3] > 8
    feet = np.where(a0[int(y1 - ch * 0.06):y1].any(axis=0))[0]
    feet_cx = int(round((feet[0] + feet[-1]) / 2)) if len(feet) else (x0 + x1) // 2
    origin = (int(feet_cx - x0), int(ch))

    def b64(img):
        buf = io.BytesIO(); img.save(buf, 'PNG'); return base64.b64encode(buf.getvalue()).decode()
    xml = ['<?xml version="1.0" encoding="utf-8"?>', f'<imgdir name="{npc_id}.img">', '  <imgdir name="info">',
           f'    <int name="dcLeft" value="{-origin[0]}"/>', f'    <int name="dcTop" value="{-ch}"/>',
           f'    <int name="dcRight" value="{cw - origin[0]}"/>', '    <int name="dcBottom" value="0"/>', '  </imgdir>']
    pdir = out / 'npc' / 'png'; pdir.mkdir(parents=True, exist_ok=True)
    for a, fs in small.items():
        xml.append(f'  <imgdir name="{a}">')
        for k, f in enumerate(fs):
            c = f.crop((x0, y0, x1, y1)); c.save(pdir / f'{a}_{k}.png')
            xml += [f'    <canvas name="{k}" width="{cw}" height="{ch}" basedata="{b64(c)}">',
                    f'      <vector name="origin" x="{origin[0]}" y="{origin[1]}"/>',
                    f'      <int name="delay" value="{delay}"/>', '    </canvas>']
        xml.append('  </imgdir>')
    xml.append('</imgdir>')
    xml_path = out / 'npc' / f'{npc_id}.img.xml'
    xml_path.write_text('\n'.join(xml), encoding='utf-8')
    print(f'canvas {cw}x{ch} origin {origin} scale {scale} delay {delay}')
    print(f'XML: {xml_path}  (HaRepacker: File > Import XML, or WzForge xml-to-img)')
    print(f'PNG frames: {pdir}')
    img_path = out / 'npc' / f'{npc_id}.img'
    if not HAVE_WZFORGE:
        print('WzForge not configured - stopping at the XML (import it with HaRepacker into Npc.wz).')
        return None
    print(wzforge('xml-to-img', str(xml_path), str(img_path)).strip().splitlines()[-1])
    v = wzforge('validate-img', str(img_path)).strip().splitlines()[-1]
    print(v)
    if 'FAILED' in v and '0 FAILED' not in v:
        raise SystemExit('validate-img reported failures - not deploying')
    return img_path


# ----------------------------------------------------------------------------- deploy
def client_running():
    r = subprocess.run(['tasklist'], capture_output=True, text=True)
    return [l.split()[0] for l in r.stdout.splitlines() if re.search(r'maple|mapleonim', l, re.I) and 'spotify' not in l.lower()]


def img_has_child(img_path, child):
    return re.search(rf'^\s{{2}}{re.escape(child)} \[Sub\]', wzforge('dump-img', img_path), re.M) is not None


def server_string_upsert(xml_path, npc_id, name):
    s = Path(xml_path).read_text(encoding='utf-8')
    entry = f'<imgdir name="{npc_id}"><string name="name" value="{name}"/></imgdir>'
    m = re.search(rf'<imgdir name="{npc_id}">.*?</imgdir>', s, re.S)
    if m:
        block = m.group(0)
        if f'value="{name}"' in block and 'name="name"' in block:
            return 'unchanged'
        if 'name="name"' in block:
            block2 = re.sub(r'<string name="name" value="[^"]*"/>', f'<string name="name" value="{name}"/>', block)
        else:
            block2 = block.replace('</imgdir>', f'<string name="name" value="{name}"/></imgdir>')
        s = s.replace(block, block2); action = 'updated'
    else:
        idx = s.rfind('</imgdir>')
        s = s[:idx] + entry + s[idx:]; action = 'added'
    Path(xml_path).write_text(s, encoding='utf-8', newline='')
    return action


def move_bak(path, backup_dir):
    p = Path(path)
    if p.exists():
        backup_dir.mkdir(parents=True, exist_ok=True)
        dst = backup_dir / p.name
        n = 1
        while dst.exists():
            dst = backup_dir / f'{p.name}.{n}'; n += 1
        shutil.move(str(p), str(dst))
        return dst


def cmd_deploy(cfg, npc_id, name, img_path=None, dry=False, commit=False):
    if not HAVE_WZFORGE or not all(PATHS.get(k) for k in ('img_client', 'wz_client', 'server_wz')):
        raise SystemExit('deploy needs npcforge.json with wzforge / img_client / wz_client / server_wz (see npcforge.example.json)')
    out = out_dir(cfg)
    img_path = Path(img_path or out / 'npc' / f'{npc_id}.img')
    if not img_path.exists():
        raise SystemExit(f'{img_path} missing - run build first')
    IMG = Path(PATHS['img_client']); WZ = Path(PATHS['wz_client']); SRV = Path(PATHS['server_wz'])
    bak = Path(PATHS['backup_dir']) / str(npc_id)
    running = client_running()
    if running:
        raise SystemExit(f'Close the game client first ({", ".join(running)}) - WzForge edits silently fail while it holds the files.')
    steps = []
    npc_exists_wz = (SRV / 'Npc.wz' / f'{npc_id}.img.xml').exists() or (IMG / 'NPC' / f'{npc_id}.img').exists()
    steps.append(f'[IMG]    copy {img_path.name} -> {IMG / "NPC"}')
    steps.append(f'[IMG]    String/Npc.img: {npc_id}/name = "{name}"')
    steps.append(f'[WZ]     Npc.wz: {"raw-replace" if npc_exists_wz else "merge (add)"} {npc_id}.img')
    steps.append(f'[WZ]     String.wz Npc: {npc_id} = "{name}"')
    steps.append(f'[SERVER] wz/Npc.wz/{npc_id}.img.xml (img-to-xml, metadata only)')
    steps.append(f'[SERVER] wz/String.wz/Npc.img.xml: {npc_id} = "{name}"')
    if commit: steps.append('[GIT]    commit the two/three server files on main + push')
    print('\n'.join(steps))
    if dry:
        print('(dry run - nothing written)'); return

    # IMG client
    shutil.copy2(img_path, IMG / 'NPC' / f'{npc_id}.img')
    simg = IMG / 'String' / 'Npc.img'
    if not img_has_child(str(simg), str(npc_id)):
        wzforge('edit-prop', str(simg), 'add-sub', str(npc_id))
    wzforge('edit-prop', str(simg), 'set-string', f'{npc_id}/name', name)
    move_bak(IMG / 'String' / 'Npc.img.bak-edit', bak)
    print('IMG client: done')

    # WZ client
    if npc_exists_wz:
        txt = wzforge('raw-replace', str(WZ / 'Npc.wz'), f'{npc_id}.img={img_path}')
    else:
        lst = out / 'npc' / 'merge_list.txt'; lst.write_text(f'{npc_id} - {name}\n')
        txt = wzforge('merge', str(img_path.parent), str(WZ / 'Npc.wz'), str(lst))
    if 'OK' not in txt and 'Saving' not in txt:
        print(txt)
    move_bak(WZ / 'Npc.wz.bak', bak)
    wzforge('edit-strings-flat', str(WZ / 'String.wz'), 'Npc', str(npc_id), name)
    move_bak(WZ / 'String.wz.bak', bak)
    # verify: extract back and compare bytes
    vdir = out / 'npc' / 'verify'; shutil.rmtree(vdir, ignore_errors=True); vdir.mkdir()
    wzforge('extract-wz', str(WZ / 'Npc.wz'), str(vdir), '--img', str(npc_id), '--raw')
    back = vdir / f'{npc_id}.img'
    if not back.exists() or back.read_bytes() != img_path.read_bytes():
        raise SystemExit('VERIFY FAILED: img inside Npc.wz differs from the built img')
    print('WZ client: done (img inside Npc.wz verified byte-identical)')

    # server
    wzforge('img-to-xml', str(img_path), str(SRV / 'Npc.wz' / f'{npc_id}.img.xml'))
    act = server_string_upsert(SRV / 'String.wz' / 'Npc.img.xml', npc_id, name)
    print(f'server XML: Npc.wz/{npc_id}.img.xml written, String Npc.img.xml {act}')
    print(f'backups (if any): {bak}')

    if commit:
        repo = SRV.parent
        files = [f'wz/Npc.wz/{npc_id}.img.xml', 'wz/String.wz/Npc.img.xml']
        subprocess.run(['git', '-C', str(repo), 'add', *files], check=True)
        msg = f'content(npc): {name} {npc_id} - animated NPC built with NpcForge\n\nCo-Authored-By: Claude Fable 5 <noreply@anthropic.com>\n'
        subprocess.run(['git', '-C', str(repo), 'commit', '-q', '-m', msg], check=True)
        subprocess.run(['git', '-C', str(repo), 'push', 'origin', 'main'], check=True)
        print('git: committed + pushed main. Run `npcforge.py mirror-vps` to mirror the same files to vps.')
    print('\nNEXT: restart the server if the name is new (String.wz is read at startup), then `!npc ' + name + '`.')


# ----------------------------------------------------------------------------- vps mirror
KEEP_SET = {'.gitignore', 'Dashboard/config.json', 'Launcher.bat', 'config.yaml',
            'dist/lib/mysql-connector-j-8.0.33.jar', 'dist/lib/mysql-connector-java-bin.jar',
            'security/RUN-install-security.bat', 'security/install-security.ps1', 'security/mpl-autoban.ps1',
            'sql/Mapleonim_Clean.sql', 'sql/Mapleonim_Full.sql'}


def cmd_mirror_vps():
    repo = Path(PATHS['server_wz']).parent
    g = lambda *a, **k: subprocess.run(['git', '-C', str(repo), *a], capture_output=True, text=True, **k)
    # files touched by the last main commit(s) that are not on vps yet: take the last commit's file list
    files = g('diff-tree', '--no-commit-id', '--name-only', '-r', 'main').stdout.split()
    files = [f for f in files if f.startswith('wz/')]
    if not files:
        raise SystemExit('last main commit touched no wz/ files - nothing to mirror')
    print('mirroring:', *files)
    g('fetch', 'origin', 'vps')
    vps = g('rev-parse', 'FETCH_HEAD').stdout.strip()
    env = dict(os.environ, GIT_INDEX_FILE=str(repo / '.git' / 'npcforge-vps-index'))
    Path(env['GIT_INDEX_FILE']).unlink(missing_ok=True)
    subprocess.run(['git', '-C', str(repo), 'read-tree', vps], check=True, env=env)
    for f in files:
        blob = g('rev-parse', f'main:{f}').stdout.strip()
        subprocess.run(['git', '-C', str(repo), 'update-index', '--add', '--cacheinfo', f'100644,{blob},{f}'], check=True, env=env)
    tree = subprocess.run(['git', '-C', str(repo), 'write-tree'], capture_output=True, text=True, env=env).stdout.strip()
    diff = g('diff', '--name-only', 'main', tree).stdout.split()
    extra = [d for d in diff if d not in KEEP_SET]
    if extra:
        Path(env['GIT_INDEX_FILE']).unlink(missing_ok=True)
        raise SystemExit('ABORT: vps would differ from main in more than the keep-set:\n  ' + '\n  '.join(extra) +
                         '\nmain is ahead of vps elsewhere - mirror by hand (see memory project_vps_surgical_mirror).')
    short = g('rev-parse', '--short', 'main').stdout.strip()
    msg = f'content(npc): mirrored from main {short} (NpcForge)\n\nCo-Authored-By: Claude Fable 5 <noreply@anthropic.com>\n'
    commit = g('commit-tree', tree, '-p', vps, '-m', msg).stdout.strip()
    r = g('push', 'origin', f'{commit}:refs/heads/vps')
    Path(env['GIT_INDEX_FILE']).unlink(missing_ok=True)
    print(r.stdout + r.stderr)
    print(f'vps <- {commit[:9]}  (diff vs main = keep-set only). Now `git pull` vps on the VPS.')


# ----------------------------------------------------------------------------- free ids
def cmd_free_id(start, count=5):
    IMG = Path(PATHS['img_client']); SRV = Path(PATHS['server_wz'])
    strings = Path(SRV / 'String.wz' / 'Npc.img.xml').read_text(encoding='utf-8')
    taken = set(int(p.stem.split('.')[0]) for p in (SRV / 'Npc.wz').glob('*.img.xml') if p.stem.split('.')[0].isdigit())
    taken |= set(int(p.stem) for p in (IMG / 'NPC').glob('*.img') if p.stem.isdigit())
    taken |= set(int(m) for m in re.findall(r'<imgdir name="(\d+)">', strings))
    free = []; i = start
    while len(free) < count and i < 9999999:
        if i not in taken: free.append(i)
        i += 1
    print('free NPC ids from', start, ':', *free)
    return free


# ----------------------------------------------------------------------------- main
def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest='cmd', required=True)
    for c in ('animate', 'build', 'deploy', 'all'):
        p = sub.add_parser(c); p.add_argument('config')
        p.add_argument('--out'); p.add_argument('--id', type=int); p.add_argument('--name')
        p.add_argument('--scale', type=float); p.add_argument('--commit', action='store_true'); p.add_argument('--dry-run', action='store_true')
    p = sub.add_parser('free-id'); p.add_argument('start', nargs='?', type=int, default=9330120)
    sub.add_parser('mirror-vps')
    p = sub.add_parser('gui'); p.add_argument('target', nargs='?')
    if len(sys.argv) == 1:                      # double-clicked / no arguments -> GUI
        sys.argv.append('gui')
    elif sys.argv[1].lower().endswith(('.png', '.json')):   # a file dropped onto the exe -> GUI on that file
        sys.argv.insert(1, 'gui')
    a = ap.parse_args()

    if a.cmd == 'free-id': cmd_free_id(a.start); return
    if a.cmd == 'mirror-vps': cmd_mirror_vps(); return
    if a.cmd == 'gui':
        sys.path.insert(0, str(HERE)); import regions_gui; regions_gui.run(a.target or None); return
    cfg = load_cfg(a.config)
    if a.cmd == 'animate': cmd_animate(cfg, a.out); return
    if not a.id: raise SystemExit('--id is required (try: npcforge.py free-id)')
    if a.cmd in ('build', 'all'):
        if a.cmd == 'all': cmd_animate(cfg, a.out)
        img = cmd_build(cfg, a.id, a.scale, a.out)
        if a.cmd == 'all' and img is None: return
    if a.cmd in ('deploy', 'all'):
        if not a.name: raise SystemExit('--name is required for deploy')
        cmd_deploy(cfg, a.id, a.name, dry=a.dry_run, commit=a.commit)


if __name__ == '__main__':
    main()
