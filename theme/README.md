# WZ Mod Builder theme kit

UI design by **'wisteria'** — the designer granted full permission and provided their tool's
complete source and assets for this reskin. Keep the credit intact.

Origins (per wisteria's own README):
- `mf/` — chrome pieces (window frame, buttons, checkboxes, scrollbar, tabs, title bar,
  window controls, arrows) adopted from the **Mob-Factory** project.
- The remaining art derives from the MapleStory v83 client UI (`UI/Basic.img` button /
  checkbox / scrollbar art, `StatusBar.img` EXP gauge) with baked-in text stripped so the
  app draws its own labels.
- `fonts/` — MapleUI TTFs, loaded process-privately (no system install needed).
- `grass_strip.png` / `signpost.png` / `slime_sip.png` — the walker-band scene from the
  bottom-right corner of wisteria's painted `background.png` (that whole 3.9 MB window is not
  shipped; only these pieces are). `grass_strip.png` is the full continuous grass run (drawn
  once, not tiled); `slime_sip.png` is the juice-sipping slime pinned into the corner.
- `app.ico` — the app/taskbar icon, generated from these wisteria assets (the `walker_pose`
  mascot centred on a cream v83 inventory slot) by the `WzModBuilder --makeicon` dev subcommand.
  Regenerate it with `WzModBuilder --makeicon theme/app.ico` if the mascot or palette changes.
