@echo off
setlocal
cd /d "%~dp0"
title NpcForge
set PY=python npcforge.py
if exist "%~dp0NpcForgeCLI.exe" set PY="%~dp0NpcForgeCLI.exe"
:menu
echo.
echo  ===== NpcForge - one PNG in, animated NPC out =====
echo   1. Region picker + live preview (GUI)
echo   2. Animate      (regions.json -^> frames + preview gif)
echo   3. Build        (frames -^> NPC XML / .img, needs an id)
echo   4. Deploy       (Mapleonim trees; needs npcforge.json)
echo   5. All-in-one   (animate + build + deploy)
echo   6. Free NPC ids
echo   7. Mirror last commit to vps
echo   0. Exit
echo.
set /p c=choice:
if "%c%"=="1" ( set /p f=PNG or regions.json (drag the file here, or blank): & %PY% gui "%f%" & goto menu )
if "%c%"=="2" ( set /p f=regions.json: & %PY% animate "%f%" & goto menu )
if "%c%"=="3" ( set /p f=regions.json: & set /p id=NPC id: & set /p sc=scale [0.13]: & if "%sc%"=="" set sc=0.13
                %PY% build "%f%" --id %id% --scale %sc% & goto menu )
if "%c%"=="4" ( set /p f=regions.json: & set /p id=NPC id: & set /p nm=NPC name: & %PY% deploy "%f%" --id %id% --name "%nm%" --commit & goto menu )
if "%c%"=="5" ( set /p f=regions.json: & set /p id=NPC id: & set /p nm=NPC name: & set /p sc=scale [0.13]: & if "%sc%"=="" set sc=0.13
                %PY% all "%f%" --id %id% --name "%nm%" --scale %sc% --commit & goto menu )
if "%c%"=="6" ( set /p s=start id [9330120]: & if "%s%"=="" set s=9330120
                %PY% free-id %s% & goto menu )
if "%c%"=="7" ( %PY% mirror-vps & goto menu )
if "%c%"=="0" exit /b
goto menu
