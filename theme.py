"""MapleStory-style chrome for tkinter, driven by the `theme/` kit (MapleUI fonts + v83 UI pieces).

Credit: UI kit designed by 'wisteria', used with permission (see theme/README.md); the chrome pieces
under theme/mf originate from the Mob-Factory project. Keep the credit intact.
"""
import ctypes, os, sys
from pathlib import Path
import tkinter as tk
from PIL import Image, ImageDraw, ImageFont, ImageTk

APP_DIR = Path(sys.executable).resolve().parent if getattr(sys, 'frozen', False) else Path(__file__).resolve().parent
THEME_DIR = APP_DIR / 'theme'

COL = {
    'window': '#ffffff', 'panel': '#f1eee1', 'panel_border': '#b7c9dc', 'header': '#4488bb',
    'text': '#1c355e', 'muted': '#66716b', 'ok': '#1d7f1d', 'warn': '#c0392b', 'entry': '#ffffff',
    'entry_border': '#9fb6cc', 'canvas': '#3a3f48', 'select': '#caffff',
}
FONT_FILES = {'title': 'MapleUI-Title01.ttf', 'button': 'MapleUI-Button01.ttf', 'label': 'MapleUI-Button02.ttf', 'small': 'MapleUI-Button03.ttf'}
FONT_FAMILY = {'title': 'MapleUI Title01', 'button': 'MapleUI Button01', 'label': 'MapleUI Button02', 'small': 'MapleUI Button03'}


def load_private_fonts():
    if sys.platform != 'win32':
        return False
    ok = True
    for f in (THEME_DIR / 'fonts').glob('*.ttf'):
        ok &= bool(ctypes.windll.gdi32.AddFontResourceExW(str(f), 0x10, 0))   # FR_PRIVATE
    return ok


class Theme:
    def __init__(self, root):
        self.root = root
        self.have_fonts = load_private_fonts()
        self._cache = {}
        self._pil = {}
        fam = FONT_FAMILY if self.have_fonts else {k: 'Segoe UI' for k in FONT_FAMILY}
        self.font = {'title': (fam['title'], 16), 'button': (fam['button'], 15), 'label': (fam['label'], 15),
                     'small': (fam['small'], 13), 'mono': ('Consolas', 11)}
        root.configure(bg=COL['window'])
        root.option_add('*Font', self.font['label'])
        root.option_add('*Listbox.font', self.font['small'])
        root.option_add('*Entry.font', self.font['label'])

    # ---------------------------------------------------------------- images
    def pil(self, rel):
        if rel not in self._pil:
            self._pil[rel] = Image.open(THEME_DIR / rel).convert('RGBA')
        return self._pil[rel]

    def photo(self, key, img):
        self._cache[key] = ImageTk.PhotoImage(img)
        return self._cache[key]

    def pil_font(self, kind, size):
        return ImageFont.truetype(str(THEME_DIR / 'fonts' / FONT_FILES[kind]), size)

    def three_slice(self, prefix, w, h=None, edge=None):
        """Horizontal 3-slice from <prefix>w/c/e (title, th) or a single strip split in thirds (btn*)."""
        try:
            L, C, R = self.pil(f'{prefix}_w.png'), self.pil(f'{prefix}_c.png'), self.pil(f'{prefix}_e.png')
        except FileNotFoundError:
            strip = self.pil(f'{prefix}.png'); e = edge or max(4, strip.width // 4)
            L, C, R = strip.crop((0, 0, e, strip.height)), strip.crop((e, 0, strip.width - e, strip.height)), strip.crop((strip.width - e, 0, strip.width, strip.height))
        h0 = L.height
        w = max(w, L.width + R.width + 1)
        out = Image.new('RGBA', (w, h0))
        out.paste(L, (0, 0))
        x = L.width
        while x < w - R.width:
            seg = C.crop((0, 0, min(C.width, w - R.width - x), h0)); out.paste(seg, (x, 0)); x += seg.width
        out.paste(R, (w - R.width, 0))
        if h and h != h0:
            out = out.resize((w, h), Image.NEAREST)
        return out

    def nine_slice(self, w, h):
        t = {n: self.pil(f'mf/bg_{n}.png') for n in ('nw', 'n', 'ne', 'w', 'c', 'e', 'sw', 's', 'se')}
        tw, th = t['nw'].size
        w, h = max(w, 2 * tw + 1), max(h, 2 * th + 1)
        img = Image.new('RGBA', (w, h))
        def fill(tile, x0, y0, x1, y1):
            for ry in range(y0, y1, tile.height):
                for rx in range(x0, x1, tile.width):
                    img.paste(tile.crop((0, 0, min(tile.width, x1 - rx), min(tile.height, y1 - ry))), (rx, ry))
        img.paste(t['nw'], (0, 0)); img.paste(t['ne'], (w - tw, 0)); img.paste(t['sw'], (0, h - th)); img.paste(t['se'], (w - tw, h - th))
        fill(t['n'], tw, 0, w - tw, th); fill(t['s'], tw, h - th, w - tw, h); fill(t['w'], 0, th, tw, h - th); fill(t['e'], w - tw, th, w, h - th)
        fill(t['c'], tw, th, w - tw, h - th)
        return img

    def text_on(self, img, text, kind='button', size=10, fill=(255, 255, 255, 255), shadow=(0, 0, 0, 110), dy=0):
        img = img.copy(); d = ImageDraw.Draw(img); f = self.pil_font(kind, size)
        tw = d.textlength(text, font=f); asc, desc = f.getmetrics()
        x = (img.width - tw) / 2; y = (img.height - (asc + desc)) / 2 + dy
        if shadow: d.text((x + 1, y + 1), text, font=f, fill=shadow)
        d.text((x, y), text, font=f, fill=fill)
        return img

    # ---------------------------------------------------------------- widgets
    def header(self, parent, text, width=None, stretch=True):
        """Blue title bar (mf/title 3-slice) with white MapleUI text. With stretch=True it re-renders to the
        parent's width whenever the parent is resized, so it always spans the panel."""
        w = width or int(self.pil_font('title', 16).getlength(text.upper())) + 40
        lbl = tk.Label(parent, bd=0, bg=COL['window'])

        def render(w):
            img = self.text_on(self.three_slice('mf/title', w), text.upper(), 'title', 16, dy=-1)
            lbl.config(image=self.photo(f'hdr:{id(lbl)}', img))
        render(w)
        if stretch:
            parent.bind('<Configure>', lambda e: render(max(w, e.width)) if e.widget is parent else None, add='+')
        return lbl

    def panel(self, parent, title=None, **kw):
        """Beige framed panel with an optional blue header on top. Returns (outer, inner)."""
        outer = tk.Frame(parent, bg=COL['window'])
        if title:
            self.header(outer, title, width=kw.pop('width', None)).pack(fill='x', anchor='w')
        inner = tk.Frame(outer, bg=COL['panel'], highlightthickness=1, highlightbackground=COL['panel_border'], padx=6, pady=6)
        inner.pack(fill='both', expand=True)
        return outer, inner

    def button(self, parent, text, command, kind='blue', width=None, height=30, size=16):
        prefix = {'blue': 'mf/btn', 'green': 'mf/btng', 'red': 'mf/btnr'}[kind]
        w = width or int(self.pil_font('button', size).getlength(text.upper())) + 30
        imgs = {}
        for state, suffix in (('normal', 'n'), ('hover', 'h'), ('pressed', 'p'), ('disabled', 'd')):
            base = self.three_slice(f'{prefix}_{suffix}', w, height, edge=6)
            imgs[state] = self.photo(f'btn:{kind}:{text}:{state}:{w}', self.text_on(base, text.upper(), 'button', size, dy=(1 if state == 'pressed' else 0)))
        return ChromeButton(parent, imgs, command, bg=parent.cget('bg'))

    def checkbox(self, parent, text, var, command=None):
        return ChromeCheck(self, parent, text, var, command)

    def radio(self, parent, text, var, value, command=None):
        return ChromeCheck(self, parent, text, var, command, value=value)

    def label(self, parent, text='', kind='label', color=None, **kw):
        return tk.Label(parent, text=text, font=self.font[kind], fg=color or COL['text'], bg=kw.pop('bg', parent.cget('bg')), **kw)

    def entry(self, parent, textvariable=None, width=10, **kw):
        return tk.Entry(parent, textvariable=textvariable, width=width, font=self.font['label'], fg=COL['text'], bg=COL['entry'],
                        relief='flat', highlightthickness=1, highlightbackground=COL['entry_border'], highlightcolor=COL['header'],
                        insertbackground=COL['text'], **kw)

    def listbox(self, parent, **kw):
        return tk.Listbox(parent, font=self.font['small'], fg=COL['text'], bg=COL['entry'], relief='flat', highlightthickness=1,
                          highlightbackground=COL['entry_border'], selectbackground=COL['header'], selectforeground='white', activestyle='none', **kw)

    def tab(self, parent, text, on, command):
        img = self.pil('tab_on.png' if on else 'tab_off.png')
        img = self.text_on(img.resize((max(img.width, int(self.pil_font('button', 11).getlength(text.upper())) + 14), img.height), Image.NEAREST), text.upper(), 'button', 11)
        lbl = tk.Label(parent, image=self.photo(f'tab:{text}:{on}', img), bd=0, bg=parent.cget('bg'), cursor='hand2')
        lbl.bind('<Button-1>', lambda e: command())
        return lbl

    def decorate_bottom(self, parent, mascot='Mob_Security_Camera.png', mascot_height=96):
        """The grass strip from the kit plus the mascot (security camera mob), pinned bottom-right."""
        try:
            grass = self.pil('grass_strip.png')
            f = tk.Frame(parent, bg=COL['window'])
            tk.Label(f, image=self.photo('grass', grass), bd=0, bg=COL['window']).pack(side='left', anchor='s')
            try:
                m = self.pil(mascot)
            except FileNotFoundError:
                m = self.pil('slime_sip.png')
            if m.height > mascot_height:
                m = m.resize((max(1, m.width * mascot_height // m.height), mascot_height), Image.LANCZOS)
            tk.Label(f, image=self.photo('mascot', m), bd=0, bg=COL['window']).pack(side='left', anchor='s', padx=(4, 0))
            return f
        except FileNotFoundError:
            return tk.Frame(parent, bg=COL['window'])


class ChromeButton:
    """Image button with normal/hover/pressed/disabled states (same contract as Mob-Factory's)."""

    def __init__(self, parent, images, command, bg):
        self.imgs, self.cmd, self.over, self.pressed, self.disabled = images, command, False, False, False
        self.widget = tk.Label(parent, image=images['normal'], bd=0, highlightthickness=0, bg=bg, cursor='hand2')
        self.widget.bind('<Enter>', lambda e: self._set('hover', over=True))
        self.widget.bind('<Leave>', lambda e: self._set('normal', over=False, pressed=False))
        self.widget.bind('<ButtonPress-1>', lambda e: self._set('pressed', pressed=True))
        self.widget.bind('<ButtonRelease-1>', self._release)

    def pack(self, **kw): self.widget.pack(**kw); return self
    def grid(self, **kw): self.widget.grid(**kw); return self

    def _set(self, state, **flags):
        if self.disabled: return
        for k, v in flags.items(): setattr(self, k, v)
        self.widget.config(image=self.imgs[state])

    def _release(self, e):
        if self.disabled: return
        was = self.pressed; self.pressed = False
        self.widget.config(image=self.imgs['hover' if self.over else 'normal'])
        if was and self.over: self.cmd()

    def set_enabled(self, on):
        self.disabled = not on
        self.widget.config(image=self.imgs['normal' if on else 'disabled'], cursor='hand2' if on else 'arrow')


class ChromeCheck:
    """Image checkbox (cb_on/cb_off); with value= it behaves as a radio button on the same variable."""

    def __init__(self, theme, parent, text, var, command=None, value=None):
        self.theme, self.var, self.value, self.command = theme, var, value, command
        self.on, self.off = theme.photo('cb_on', theme.pil('mf/cb_on.png')), theme.photo('cb_off', theme.pil('mf/cb_off.png'))
        self.widget = tk.Frame(parent, bg=parent.cget('bg'), cursor='hand2')
        self.box = tk.Label(self.widget, image=self.off, bd=0, bg=parent.cget('bg')); self.box.pack(side='left')
        self.lbl = theme.label(self.widget, text.upper(), bg=parent.cget('bg')); self.lbl.pack(side='left', padx=(4, 0))
        for w in (self.widget, self.box, self.lbl): w.bind('<Button-1>', self.toggle)
        var.trace_add('write', lambda *a: self.refresh()); self.refresh()

    def pack(self, **kw): self.widget.pack(**kw); return self
    def grid(self, **kw): self.widget.grid(**kw); return self

    def toggle(self, e=None):
        if self.value is not None: self.var.set(self.value)
        else: self.var.set(not bool(self.var.get()))
        if self.command: self.command()

    def refresh(self):
        state = (self.var.get() == self.value) if self.value is not None else bool(self.var.get())
        self.box.config(image=self.on if state else self.off)
