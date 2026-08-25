# NpcForge
<img width="1462" height="975" alt="image" src="https://github.com/user-attachments/assets/b2e015f5-7bb0-4919-aedf-4400c89b3f13" />

Turn **one** character PNG into a living MapleStory NPC: swaying hair, a waving arm, a talking mouth -
no frame-by-frame drawing. You mark three kinds of regions on the picture, the tool generates the
`stand` and `speak` animations, packs them into an `Npc.wz` XML (or `.img`), and - if you configure
your trees - ships the NPC into the game.

Made for v83-era servers (tested on a v83 client), but the output is plain WZ XML, so any version
that reads `Npc.wz/<id>.img` with `stand`/`speak` canvases works.

## How it works (no AI involved)

Plain Python (Pillow + NumPy) doing classic **cut-out animation**: the still is split into layers by
the regions you mark, then each layer is moved with deterministic math - a per-row sine displacement
for hair/leaves (amplitude grows with distance from the root, so the root never tears), an affine
rotation around a pivot for a limb (nearest-neighbour, pixels stay crisp), and a drawn pixel-grid
mouth for `speak`. Same input, same output, every time.

## Requirements

* **Release zip:** nothing - run `NpcForge.exe` (GUI) or `NpcForgeCLI.exe <command>` (see below).
  `NpcForge.bat` gives you a menu over the CLI.
* **From source:** Python 3.10+ with `pip install -r requirements.txt` (Pillow, numpy, scipy,
  opencv-contrib-python-headless for the clone-stamp inpainting). tkinter ships with Python on Windows.
  `build-exe.bat` rebuilds the release folder (`dist\NpcForge`) with PyInstaller.
* Optional: [WzForge](../WzForge) for direct `.img` output, validation and one-shot deploy.
  Without it you get the XML + PNG frames and import the XML with HaRepacker (File > Import > XML).

## 1. Draw the regions

```
NpcForge.bat  ->  1        (or: python npcforge.py gui character.png)
```

* **Sway** (green): the part that should wave in the wind - hair, leaves, a flame, a cape. The box
  bottom is the root (set `root: top` for something hanging down). Amplitude grows toward the tips,
  so the root never tears.
* **Limb** (blue): an arm/tail that should move. Draw the box around the limb, then **click the joint**
  it rotates around (the shoulder). The limb is drawn behind the body and the box is extended
  `overlap` px into the body so the seam stays hidden.
* **Mouth** (pink): a box around the closed mouth. `speak` frames redraw it as an open mouth using the
  colours found in the box (outline = mouth colour, inside = darkened).

* **Eyes** (yellow): a box around the eyes. One frame per loop shows them closed (a blink); set
  `"blink": {"box": [...], "at": [21]}` in the JSON to choose the frame(s).

Tick **polygon** to outline a region point by point instead of a box (double-click closes, Esc
cancels) - use it for limbs that run along the body, so the torso is not cut with them. Whatever a
limb still takes out of the torso is filled in automatically from the neighbouring body pixels
(`"fill_body": false` in the JSON turns that off), so the body stays whole when the limb moves away.

Things you set in the JSON (no GUI yet):

* `"root": "left"` / `"right"` on a sway box: the wave runs sideways - headband tails, a scarf.
* `"keyframes": [[frame, angle], ...]` on a limb: a scripted move instead of a wag, e.g. a sword
  stab `[[0,0],[5,85],[8,88],[14,88],[19,0]]` (smooth in-between, loops).
* `"parent": 0` on a limb: a two-bone limb - the blade rides in the hand of limb 0 and adds its own
  rotation around its own pivot. `"clip_below": 1132` hides whatever goes under the ground line.
* `"flip": [{"box"/"poly": ..., "frames": [[5, 31]]}]`: the region is drawn mirrored during those frames -
  a wolf turning its head to look back at its owner (`examples/wolf_ranger.json`).
* Holes a moving part leaves in the body are "continued" automatically, clone-stamp style: OpenCV's
  SHIFTMAP inpainting when `opencv-contrib-python-headless` is installed (it is in the exe), a built-in
  exemplar fill otherwise. `"extend": 10` additionally clones a limb a few px past its cut line so a
  bent torso shows no straight edge (off by default - on a strap-covered arm it clones the strap).
* AI exports with a fake checkerboard background: `python examples/strip_checker.py in.png out.png`
  turns the checker into real transparency (keeps white flowers, blades, eyes).

Press **Preview** to see `stand` and `speak` looping. Numbers on the right (frames, delay, sway
amplitude, limb angles) apply to new boxes; edit the saved `regions.json` for fine control.
`Save regions.json` stores everything next to the PNG.

Working examples in `examples/`: `leek_small` (hair + finger + mouth), `beach_leek`, `ninja_leek`
and `ronin_leek` (headband tails, two-bone sword stab into the ground, blink), `wolf_ranger` (a
flipped wolf head looking back, head tilt, a lean with the belt seam inpainted).

## 2. Animate / build

```
python npcforge.py animate examples/leek.json            # frames/, stand_preview.gif, speak_preview.gif, *_sheet.png
python npcforge.py build   examples/leek.json --id 9330119 --scale 0.13
```

`build` downsizes every frame with the same scale, crops all of them to one shared bounding box,
puts the origin at bottom-centre of the feet and writes:

* `<name>_out/npc/<id>.img.xml` - classic HaRepacker XML with base64 canvases (`info/dc*`, `stand/N`,
  `speak/N`, each canvas with `origin` + `delay`)
* `<name>_out/npc/png/` - the final frames as PNG, if you prefer to assemble by hand
* `<name>_out/npc/<id>.img` - only when WzForge is configured (and it is validated: every canvas decoded)

Size guide: a normal v83 NPC is 60-90 px tall; big "feature" NPCs 130-180. `--scale 0.13` turned a
1100x1425 source into 132x173.

## 3. Deploy (Mapleonim layout - optional)

Copy `npcforge.example.json` to `npcforge.json` and fill in your paths. Then:

```
python npcforge.py free-id 9330120                      # first ids free in Npc.wz + String + IMG tree
python npcforge.py deploy examples/leek.json --id 9330119 --name LEEK [--commit] [--dry-run]
python npcforge.py all    examples/leek.json --id 9330119 --name LEEK --scale 0.13
```

Deploy does, in order (and refuses to run while the game client is open, because WZ edits silently
fail then):

1. IMG client: copies `<id>.img` into `Data/NPC`, adds `<id>/name` to `Data/String/Npc.img`
2. WZ client: `merge` (new id) or `raw-replace` (existing) into `Npc.wz`, name into `String.wz`,
   then extracts the img back and checks it is byte-identical
3. Server: metadata-only `wz/Npc.wz/<id>.img.xml` + the `<imgdir>` in `wz/String.wz/Npc.img.xml`
4. `--commit`: commits + pushes those server files on `main`; `mirror-vps` copies the same files onto
   the `vps` branch with the usual keep-set check

WzForge's `.bak` files are moved to `backup_dir/<id>/`. Restart the server after adding a new name
(String.wz is read at startup), then `!npc <name>`.

## Look and feel

The GUI uses the MapleStory-style kit in `theme/` (MapleUI fonts, v83 UI pieces, the grass-and-slime
corner). UI design by **wisteria**, shipped with GodlyPac's WZ Mod Builder; the chrome pieces under
`theme/mf` come from the Mob-Factory project. See `theme/README.md` and keep the credit intact.
The fonts are loaded process-privately (nothing gets installed on your system).

## What it cannot do

Cut-out animation moves the pixels that are there. A pose that needs pixels the still does not have -
an arm that is folded against the torso reaching out to pet a wolf, a face turning to a new angle -
cannot be invented; you get a rotated block of torso texture instead. For those, draw (or generate)
a second still in the target pose; the rig can then switch between stills.

## Tips from the first NPC (LEEK)

* AI "pixel art" is usually not on a pixel grid - work at full resolution, downscale once at the end.
* If a piece of the body only made sense because a limb covered it (a collar corner over a raised
  sleeve), it turns into a floating fragment when the limb moves. Erase it from the PNG first.
* Rotate a limb around the middle of the shoulder plate, not around the seam - the cut stays hidden.
* Poses that need a different silhouette (hand on hip) are best made by mirroring the other arm; that
  is a custom script, see the LEEK notes, not something the boxes can express.
<img width="3760" height="1128" alt="stand_sheet" src="https://github.com/user-attachments/assets/f7dd50dc-e2f2-41e2-94b4-a017fbc6c803" />
