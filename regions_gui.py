"""NpcForge region picker - MapleStory-style UI (theme kit): draw boxes on the PNG, preview live, save regions.json."""
import json, sys, threading
from pathlib import Path
import tkinter as tk
from tkinter import filedialog, messagebox
from PIL import Image, ImageTk

HERE = Path(sys.executable).resolve().parent if getattr(sys, 'frozen', False) else Path(__file__).resolve().parent
sys.path.insert(0, str(Path(__file__).resolve().parent))
from theme import Theme, COL

KINDS = [('sway', 'Sway: hair / leaves / flame', '#38d430'),
         ('wag', 'Limb: arm / tail  (+ click pivot)', '#3aa0ff'),
         ('mouth', 'Mouth box', '#ff5cc8'),
         ('blink', 'Eyes box (blink)', '#ffd23a')]
NEW_CFG = {'image': '', 'delay': 120, 'stand_frames': 10, 'speak_frames': 8, 'sway': [], 'wag': [], 'mouth': None, 'blink': None, 'scale': 0.13}


class Picker:
    def __init__(self, target=None):
        self.root = tk.Tk(); self.root.title('NpcForge - Region Picker'); self.root.geometry('1180x860'); self.root.minsize(980, 700)
        for ico in (HERE / 'npcforge.ico', HERE / 'theme' / 'app.ico'):
            try: self.root.iconbitmap(str(ico)); break
            except Exception: pass
        self.T = Theme(self.root)
        self.cfg = json.loads(json.dumps(NEW_CFG)); self.cfg_path = None; self.im = None
        self.scale = 1.0; self.mode = 'sway'; self.drag = None; self.rubber = None; self.preview_win = None; self.poly_pts = []
        self._build()
        if target:
            t = Path(target)
            if t.suffix.lower() == '.json': self.load_json(t)
            else: self.load_image(t)
        self.root.bind('<Configure>', self._on_resize)
        self.root.mainloop()

    # ------------------------------------------------------------------ layout
    def _build(self):
        T = self.T; root = self.root
        # background 9-slice on a canvas that fills the window
        self.bg = tk.Canvas(root, bd=0, highlightthickness=0, bg=COL['window']); self.bg.place(x=0, y=0, relwidth=1, relheight=1)
        body = tk.Frame(root, bg=COL['window']); body.place(x=10, y=8, relwidth=1, relheight=1, width=-20, height=-16)

        # top bar: search-like path + actions
        top = tk.Frame(body, bg=COL['window']); top.pack(fill='x', pady=(0, 6))
        T.label(top, 'NPCFORGE', 'title', color=COL['header']).pack(side='left', padx=(2, 12))
        self.path_var = tk.StringVar(value='(no image loaded)')
        T.entry(top, self.path_var, width=48, state='readonly', readonlybackground=COL['entry']).pack(side='left', padx=(0, 8))
        T.button(top, 'Open PNG', self.open_png).pack(side='left', padx=2)
        T.button(top, 'Open JSON', self.open_json).pack(side='left', padx=2)
        T.button(top, 'Save JSON', self.save_json, kind='green').pack(side='left', padx=2)
        T.button(top, 'Preview', self.preview, kind='green').pack(side='left', padx=(12, 2))
        T.button(top, 'Undo', self.undo).pack(side='left', padx=2)
        T.button(top, 'Clear', self.clear, kind='red').pack(side='left', padx=2)

        mid = tk.Frame(body, bg=COL['window']); mid.pack(fill='both', expand=True)
        # left column
        left = tk.Frame(mid, bg=COL['window'], width=300); left.pack(side='left', fill='y', padx=(0, 8)); left.pack_propagate(False)
        outer, mode = T.panel(left, 'Draw mode', width=300); outer.pack(fill='x')
        self.mode_var = tk.StringVar(value='sway')
        for k, label, col in KINDS:
            T.radio(mode, label, self.mode_var, k, command=lambda k=k: setattr(self, 'mode', k)).pack(anchor='w', pady=1)
        self.poly_var = tk.BooleanVar(value=False)
        T.checkbox(mode, 'polygon (click points, dbl-click ends)', self.poly_var, command=self.cancel_poly).pack(anchor='w', pady=(4, 0))
        self.hint = T.label(mode, 'DRAG A BOX ON THE PICTURE', 'small', color=COL['muted'], wraplength=275, justify='left'); self.hint.pack(anchor='w', pady=(6, 0))

        outer, opts = T.panel(left, 'Options', width=300); outer.pack(fill='x', pady=(8, 0))
        self.vars = {}
        def num(label, key, default, width=7):
            f = tk.Frame(opts, bg=COL['panel']); f.pack(anchor='w', fill='x', pady=1)
            T.label(f, label.upper(), 'small').pack(side='left'); v = tk.StringVar(value=str(default)); self.vars[key] = v
            T.entry(f, v, width=width).pack(side='right')
        num('stand frames', 'stand_frames', 10); num('speak frames', 'speak_frames', 8); num('delay ms', 'delay', 120); num('scale (0.13 = LEEK)', 'scale', 0.13)
        T.label(opts, 'SWAY (NEW BOXES)', 'label', color=COL['header']).pack(anchor='w', pady=(6, 0))
        num('tip amplitude px', 'amp', 22); num('root: bottom / top', 'root', 'bottom')
        T.label(opts, 'LIMB (NEW BOXES)', 'label', color=COL['header']).pack(anchor='w', pady=(6, 0))
        num('angles min,max', 'angles', '0,6'); num('speak angles', 'speak_angles', '0,8'); num('overlap px', 'overlap', 40)
        self.behind_var = tk.BooleanVar(value=True); T.checkbox(opts, 'limb behind body', self.behind_var).pack(anchor='w', pady=(2, 0))
        T.label(opts, 'MOUTH', 'label', color=COL['header']).pack(anchor='w', pady=(6, 0)); num('cell px', 'cell', 10)

        outer, reg = T.panel(left, 'Regions', width=300); outer.pack(fill='both', expand=True, pady=(8, 0))
        self.listbox = T.listbox(reg, height=8); self.listbox.pack(fill='both', expand=True)

        # centre: picture
        centre = tk.Frame(mid, bg=COL['window']); centre.pack(side='left', fill='both', expand=True)
        outer, pic = T.panel(centre, 'Picture'); outer.pack(fill='both', expand=True)
        self.canvas = tk.Canvas(pic, bg=COL['canvas'], bd=0, highlightthickness=0, cursor='crosshair'); self.canvas.pack(fill='both', expand=True)
        self.canvas.bind('<ButtonPress-1>', self.on_down); self.canvas.bind('<B1-Motion>', self.on_move); self.canvas.bind('<ButtonRelease-1>', self.on_up)
        self.canvas.bind('<Double-Button-1>', self.on_double); root.bind('<Escape>', self.cancel_poly)
        self._redraw_job = None
        def on_canvas_resize(e):
            if self._redraw_job: self.root.after_cancel(self._redraw_job)
            self._redraw_job = self.root.after(40, self.redraw)
        self.canvas.bind('<Configure>', on_canvas_resize)

        # bottom: log + mascot
        bottom = tk.Frame(body, bg=COL['window']); bottom.pack(fill='x', pady=(6, 0))
        outer, logp = T.panel(bottom, 'Log'); outer.pack(side='left', fill='x', expand=True)
        self.log = T.listbox(logp, height=3); self.log.pack(fill='x')
        T.decorate_bottom(bottom).pack(side='right', anchor='s', padx=(8, 0))
        self.say('draw boxes: green = sway, blue = limb (then click its pivot), pink = mouth. preview any time.')

    def _on_resize(self, e):
        if e.widget is self.root:
            w, h = self.root.winfo_width(), self.root.winfo_height()
            if w > 60 and h > 60:
                self.bg_photo = ImageTk.PhotoImage(self.T.nine_slice(w, h)); self.bg.delete('all'); self.bg.create_image(0, 0, anchor='nw', image=self.bg_photo)
            self.root.after_idle(self.redraw)

    def say(self, msg):
        self.log.insert('end', msg.upper()); self.log.see('end')

    # ------------------------------------------------------------------ files
    def open_png(self):
        p = filedialog.askopenfilename(filetypes=[('PNG', '*.png')])
        if p: self.load_image(Path(p))

    def load_image(self, path):
        self.im = Image.open(path).convert('RGBA'); self.cfg = json.loads(json.dumps(NEW_CFG)); self.cfg['image'] = path.name
        self.cfg_path = path.with_suffix('.json'); self.path_var.set(str(path)); self.say(f'loaded {path.name} {self.im.width}x{self.im.height}'); self.redraw()

    def open_json(self):
        p = filedialog.askopenfilename(filetypes=[('regions json', '*.json')])
        if p: self.load_json(Path(p))

    def load_json(self, path):
        self.cfg = {**json.loads(json.dumps(NEW_CFG)), **json.loads(path.read_text(encoding='utf-8'))}; self.cfg_path = path
        img = Path(self.cfg['image'])
        if not img.is_absolute(): img = path.parent / img
        self.im = Image.open(img).convert('RGBA'); self.path_var.set(str(img))
        for k in ('stand_frames', 'speak_frames', 'delay', 'scale'):
            if k in self.cfg: self.vars[k].set(str(self.cfg[k]))
        self.say(f'loaded {path.name} ({len(self.cfg["sway"])} sway, {len(self.cfg["wag"])} limb, mouth {"yes" if self.cfg.get("mouth") else "no"})'); self.redraw()

    def collect(self):
        for k in ('stand_frames', 'speak_frames', 'delay'): self.cfg[k] = int(float(self.vars[k].get()))
        self.cfg['scale'] = float(self.vars['scale'].get()); return self.cfg

    def save_json(self):
        if not self.im: return
        self.collect()
        p = filedialog.asksaveasfilename(defaultextension='.json', initialfile=self.cfg_path.name, initialdir=self.cfg_path.parent)
        if not p: return
        self.cfg_path = Path(p); self.cfg_path.write_text(json.dumps(self.cfg, indent=2), encoding='utf-8'); self.say(f'saved {self.cfg_path.name}')

    # ------------------------------------------------------------------ drawing
    def redraw(self):
        if not self.im: return
        cw, ch = max(100, self.canvas.winfo_width()), max(100, self.canvas.winfo_height())
        self.scale = min(cw / self.im.width, ch / self.im.height)          # zoom small sprites up, big ones down
        sz = (max(1, int(self.im.width * self.scale)), max(1, int(self.im.height * self.scale)))
        bg = Image.new('RGBA', sz, (58, 63, 72, 255)); bg.alpha_composite(self.im.resize(sz, Image.NEAREST if self.scale > 1 else Image.LANCZOS))
        self.tk_im = ImageTk.PhotoImage(bg); self.canvas.delete('all'); self.canvas.create_image(0, 0, anchor='nw', image=self.tk_im)
        self.listbox.delete(0, 'end'); s = self.scale
        def geom(r): return f'poly {len(r["poly"])} pts' if r.get('poly') else f'box {r.get("box")}'
        for i, r in enumerate(self.cfg['sway']):
            self._box(r, KINDS[0][2], f'SWAY {i}'); self.listbox.insert('end', f'SWAY {i}  {geom(r)}  amp {r.get("amp")}  root {r.get("root")}')
        for i, r in enumerate(self.cfg['wag']):
            self._box(r, KINDS[1][2], f'LIMB {i}')
            if r.get('pivot'):
                px, py = r['pivot']; self.canvas.create_oval(px * s - 5, py * s - 5, px * s + 5, py * s + 5, outline=KINDS[1][2], width=2)
            extra = ' keyframes' if r.get('keyframes') else ''; extra += f' parent {r["parent"]}' if r.get('parent') is not None else ''
            self.listbox.insert('end', f'LIMB {i}  {geom(r)}  pivot {r.get("pivot")}  angles {r.get("angles")}{extra}')
        if self.cfg.get('mouth'):
            self._box(self.cfg['mouth'], KINDS[2][2], 'MOUTH'); self.listbox.insert('end', f'MOUTH  {geom(self.cfg["mouth"])}')
        if self.cfg.get('blink'):
            self._box(self.cfg['blink'], KINDS[3][2], 'EYES'); self.listbox.insert('end', f'BLINK  {geom(self.cfg["blink"])}')

    def _box(self, r, col, label):
        """Outline a region (box or polygon) on the canvas."""
        s = self.scale
        if isinstance(r, dict) and r.get('poly'):
            pts = [(p[0] * s, p[1] * s) for p in r['poly']]
            self.canvas.create_polygon(pts, outline=col, fill='', width=2)
            self.canvas.create_text(pts[0][0] + 3, pts[0][1] + 3, text=label, anchor='nw', fill=col, font=self.T.font['small'])
            return
        b = r['box'] if isinstance(r, dict) else r
        self.canvas.create_rectangle(b[0] * s, b[1] * s, b[2] * s, b[3] * s, outline=col, width=2)
        self.canvas.create_text(b[0] * s + 3, b[1] * s + 3, text=label, anchor='nw', fill=col, font=self.T.font['small'])

    def _add_region(self, geom):
        """geom = {'box': [...]} or {'poly': [[x,y],...]} in image pixels; adds it under the current draw mode."""
        v = self.vars
        try:
            if self.mode == 'sway':
                self.cfg['sway'].append({**geom, 'root': v['root'].get().strip() or 'bottom', 'amp': float(v['amp'].get()), 'wave': 1.6, 'lift': 0.125})
            elif self.mode == 'wag':
                a = [float(t) for t in v['angles'].get().split(',')]; sa = [float(t) for t in v['speak_angles'].get().split(',')]
                self.cfg['wag'].append({**geom, 'pivot': None, 'angles': a, 'speak_angles': sa, 'phase': 60, 'behind': bool(self.behind_var.get()),
                                        'overlap': int(float(v['overlap'].get())), 'speak_speed': 2})
                self.hint.config(text='NOW CLICK THE PIVOT (THE JOINT THE LIMB ROTATES AROUND)'); self.say('limb added - click its pivot')
            elif self.mode == 'blink':
                self.cfg['blink'] = dict(geom)
            else:
                self.cfg['mouth'] = {**geom, 'cell': int(float(v['cell'].get()))}
        except ValueError as ex:
            messagebox.showerror('NpcForge', f'bad number in options: {ex}'); return
        self.redraw()

    def on_down(self, e):
        if not self.im: return
        x, y = e.x / self.scale, e.y / self.scale
        if self.mode == 'wag' and self.cfg['wag'] and self.cfg['wag'][-1].get('pivot') is None:
            self.cfg['wag'][-1]['pivot'] = [int(x), int(y)]; self.say(f'pivot set at {int(x)},{int(y)}'); self.hint.config(text='DRAG A BOX ON THE PICTURE'); self.redraw(); return
        if self.poly_var.get():                                   # polygon mode: collect points
            self.poly_pts.append((int(x), int(y)))
            s = self.scale; pts = [(px * s, py * s) for px, py in self.poly_pts]
            self.canvas.delete('polydraft')
            if len(pts) > 1: self.canvas.create_line(pts, fill='#ffffff', dash=(3, 3), tags='polydraft')
            for px, py in pts: self.canvas.create_oval(px - 3, py - 3, px + 3, py + 3, outline='#ffffff', tags='polydraft')
            self.hint.config(text=f'POLYGON: {len(self.poly_pts)} POINTS - DOUBLE-CLICK TO CLOSE, ESC TO CANCEL')
            return
        self.drag = (e.x, e.y); self.rubber = self.canvas.create_rectangle(e.x, e.y, e.x, e.y, outline='#ffffff', dash=(3, 3))

    def on_double(self, e):
        if self.poly_var.get() and len(self.poly_pts) >= 3:
            pts = self.poly_pts[:]; self.poly_pts = []; self.canvas.delete('polydraft'); self.drag = None
            if self.rubber: self.canvas.delete(self.rubber); self.rubber = None
            if len(pts) > 1 and abs(pts[-1][0] - pts[-2][0]) < 3 and abs(pts[-1][1] - pts[-2][1]) < 3: pts.pop()   # the double-click's own duplicate point
            self.hint.config(text='DRAG A BOX ON THE PICTURE'); self._add_region({'poly': [list(p) for p in pts]})

    def cancel_poly(self, e=None):
        self.poly_pts = []; self.canvas.delete('polydraft'); self.hint.config(text='DRAG A BOX ON THE PICTURE')

    def on_move(self, e):
        if self.drag and not self.poly_var.get(): self.canvas.coords(self.rubber, self.drag[0], self.drag[1], e.x, e.y)

    def on_up(self, e):
        if not self.drag or self.poly_var.get(): return
        x0, y0 = self.drag; self.drag = None; self.canvas.delete(self.rubber)
        if abs(e.x - x0) < 4 or abs(e.y - y0) < 4: return
        box = [int(min(x0, e.x) / self.scale), int(min(y0, e.y) / self.scale), int(max(x0, e.x) / self.scale), int(max(y0, e.y) / self.scale)]
        self._add_region({'box': box})

    def undo(self):
        if self.cfg.get('blink'): self.cfg['blink'] = None
        elif self.cfg.get('mouth'): self.cfg['mouth'] = None
        elif self.cfg['wag']: self.cfg['wag'].pop()
        elif self.cfg['sway']: self.cfg['sway'].pop()
        self.hint.config(text='DRAG A BOX ON THE PICTURE'); self.redraw()

    def clear(self):
        self.cfg['sway'], self.cfg['wag'], self.cfg['mouth'], self.cfg['blink'] = [], [], None, None; self.redraw()

    # ------------------------------------------------------------------ preview
    def preview(self):
        if not self.im: return
        if any(w.get('pivot') is None for w in self.cfg['wag']):
            messagebox.showwarning('NpcForge', 'a limb has no pivot yet - click it'); return
        self.collect()
        tmp = self.cfg_path or Path(self.im.filename).with_suffix('.json')
        tmp.write_text(json.dumps(self.cfg, indent=2), encoding='utf-8'); self.cfg_path = tmp
        self.say('rendering preview...'); self.root.update()
        import npcforge
        cfg = npcforge.load_cfg(tmp); rig = npcforge.Rig(cfg)
        frames = {'stand': rig.stand(), 'speak': rig.speak()}
        self.show_anim(frames, cfg['delay']); self.say(f'preview ready - regions saved to {tmp.name}')

    def show_anim(self, frames, delay):
        if self.preview_win and self.preview_win.winfo_exists(): self.preview_win.destroy()
        win = tk.Toplevel(self.root); win.title('NpcForge - preview'); win.configure(bg=COL['window']); self.preview_win = win
        sc = min(1.0, 420 / frames['stand'][0].height); cols = {}
        for name in ('stand', 'speak'):
            outer, inner = self.T.panel(win, name); outer.pack(side='left', padx=6, pady=6)
            ims = []
            for f in frames[name]:
                s = f.resize((max(1, int(f.width * sc)), max(1, int(f.height * sc))), Image.LANCZOS)
                bg = Image.new('RGBA', s.size, (58, 63, 72, 255)); bg.alpha_composite(s); ims.append(ImageTk.PhotoImage(bg))
            lbl = tk.Label(inner, image=ims[0], bd=0, bg=COL['panel']); lbl.pack(); lbl.ims = ims; cols[name] = (lbl, ims)
        state = {'k': 0}
        def tick():
            if not win.winfo_exists(): return
            for lbl, ims in cols.values(): lbl.config(image=ims[state['k'] % len(ims)])
            state['k'] += 1; win.after(delay, tick)
        tick()


def run(target=None):
    Picker(target)


if __name__ == '__main__':
    run(sys.argv[1] if len(sys.argv) > 1 else None)
