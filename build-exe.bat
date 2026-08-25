@echo off
setlocal
cd /d "%~dp0"
echo Building NpcForge.exe + NpcForgeCLI.exe (PyInstaller) ...
python -m PyInstaller --noconfirm --clean NpcForge.spec || exit /b 1
set OUT=dist\NpcForge
rd /s /q build 2>nul
xcopy /e /i /y theme "%OUT%\theme" >nul
xcopy /e /i /y examples "%OUT%\examples" >nul
for /d %%d in ("%OUT%\examples\*_out") do rd /s /q "%%d"
copy /y README.md "%OUT%\" >nul
copy /y npcforge.example.json "%OUT%\" >nul
copy /y NpcForge.bat "%OUT%\" >nul
copy /y npcforge.ico "%OUT%\" >nul
copy /y screenshot.png "%OUT%\" >nul 2>nul
echo.
echo Done: %OUT%\NpcForge.exe (GUI)  %OUT%\NpcForgeCLI.exe (CLI)  -  npcforge.json is NOT copied on purpose.
