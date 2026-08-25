# MapleStory-style UI kit

UI design by **'wisteria'** - the designer granted full permission and provided the complete source and
assets for this reskin. Keep the credit intact.

Origins (per wisteria's own notes):
- `mf/` - chrome pieces (window frame, buttons, checkboxes, scrollbar, tabs, title bar, window
  controls, arrows) adopted from the **Mob-Factory** project.
- The remaining art derives from the MapleStory v83 client UI (`UI/Basic.img` button / checkbox /
  scrollbar art, `StatusBar.img` EXP gauge) with baked-in text stripped so the app draws its own labels.
- `fonts/` - MapleUI TTFs, loaded process-privately (no system install needed).
- `grass_strip.png` / `signpost.png` / `slime_sip.png` - the walker-band scene from the bottom-right
  corner of wisteria's painted background (that whole 3.9 MB image is not shipped; only these pieces
  are). `grass_strip.png` is the full continuous grass run (drawn once, not tiled).
- `app.ico` - an app/taskbar icon generated from these assets. NpcForge ships its own icon
  (`npcforge.ico`) and uses that one instead.
