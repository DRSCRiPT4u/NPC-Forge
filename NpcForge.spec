# -*- mode: python ; coding: utf-8 -*-
# Two executables from one analysis: NpcForge.exe (windowed GUI) and NpcForgeCLI.exe (console).
# theme/, examples/, README and the json templates are copied NEXT TO the exe by build-exe.bat
# (the code resolves them from the exe folder), so nothing from there is embedded here.
a = Analysis(['npcforge.py'], pathex=['.'], binaries=[], datas=[],
             hiddenimports=['regions_gui', 'theme', 'PIL.ImageTk', 'PIL._tkinter_finder', 'cv2', 'scipy.ndimage'],
             hookspath=[], runtime_hooks=[], excludes=['matplotlib', 'pandas'], noarchive=False)
pyz = PYZ(a.pure)
gui = EXE(pyz, a.scripts, [], exclude_binaries=True, name='NpcForge', console=False, icon='npcforge.ico',
          upx=False, disable_windowed_traceback=False)
cli = EXE(pyz, a.scripts, [], exclude_binaries=True, name='NpcForgeCLI', console=True, icon='npcforge.ico', upx=False)
coll = COLLECT(gui, cli, a.binaries, a.datas, strip=False, upx=False, name='NpcForge')
