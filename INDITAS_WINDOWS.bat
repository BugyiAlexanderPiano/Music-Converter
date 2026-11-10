@echo off
REM ==================================================================
REM  AuraWave Genos Studio Pro - inditas Windowson
REM  Windows 11 / 10 / 8.1 / 7  (Windows XP-n a modern Python nem fut)
REM  Dupla kattintassal inditsd.
REM ==================================================================
setlocal
title AuraWave Genos Studio Pro
cd /d "%~dp0"

echo.
echo   ===============================================
echo      AuraWave Genos Studio Pro - inditas
echo   ===============================================
echo.

REM ---- Windows verzio ellenorzese (XP = 5.1, Vista = 6.0) ----------
ver | find " 5.1." >nul && goto :xp
ver | find " 5.2." >nul && goto :xp
ver | find " 6.0." >nul && goto :xp
set "WIN7="
ver | find " 6.1." >nul && set "WIN7=1"

REM ---- Python keresese --------------------------------------------
set "PY="
py -3 -c "import sys" >nul 2>&1 && set "PY=py -3"
if not defined PY (
    python -c "import sys; sys.exit(0 if sys.version_info[0]==3 else 1)" >nul 2>&1 && set "PY=python"
)
if not defined PY goto :nopython

REM ---- Verzio: legalabb 3.8 -----------------------------------------
%PY% -c "import sys; sys.exit(0 if sys.version_info>=(3,8) else 1)" >nul 2>&1
if errorlevel 1 (
    echo   [!] A telepitett Python tul regi. Legalabb 3.8 kell.
    goto :nopython
)
for /f "delims=" %%v in ('%PY% -c "import sys;print(sys.version.split()[0])"') do echo   Python %%v talalhato.

REM ---- tkinter ellenorzese ------------------------------------------
%PY% -c "import tkinter" >nul 2>&1
if errorlevel 1 (
    echo.
    echo   [!] A Pythonbol hianyzik a "tcl/tk and IDLE" osszetevo.
    echo       Telepitsd ujra a Pythont a python.org-rol, es hagyd bekapcsolva
    echo       a "tcl/tk and IDLE" opciot.
    goto :fail
)

REM ---- numpy (csak elso inditaskor kell internet) --------------------
%PY% -c "import numpy" >nul 2>&1
if errorlevel 1 (
    echo   Elso inditas: a szukseges csomag ^(numpy^) telepitese...
    %PY% -m pip install --user --upgrade pip >nul 2>&1
    %PY% -m pip install --user -r requirements.txt
    %PY% -c "import numpy" >nul 2>&1
    if errorlevel 1 (
        echo.
        echo   [!] A numpy telepitese nem sikerult. Van internetkapcsolat?
        goto :fail
    )
)

REM ---- Inditas --------------------------------------------------------
echo   Program inditasa...
%PY% main.py
if errorlevel 1 goto :fail
exit /b 0

:nopython
echo.
echo   [!] Nem talalhato megfelelo Python ^(3.8 vagy ujabb^).
echo.
if defined WIN7 (
    echo   Windows 7-hez a Python 3.8.10 az utolso hivatalos verzio:
    echo   https://www.python.org/downloads/release/python-3810/
    echo   ^(Windows installer 64-bit vagy 32-bit^)
    start "" "https://www.python.org/downloads/release/python-3810/"
) else (
    where winget >nul 2>&1
    if not errorlevel 1 (
        echo   Telepites a Windows csomagkezelovel ^(winget^)...
        winget install -e --id Python.Python.3.12 --accept-package-agreements --accept-source-agreements
        echo.
        echo   Kesz. Zard be ezt az ablakot, es inditsd ujra ezt a fajlt.
        goto :fail
    )
    echo   Toltsd le innen: https://www.python.org/downloads/
    start "" "https://www.python.org/downloads/"
)
echo.
echo   FONTOS: telepiteskor pipald be az "Add python.exe to PATH" opciot,
echo   majd inditsd ujra ezt a fajlt.
goto :fail

:xp
echo   [!] Ez a Windows verzio ^(XP / Vista^) nem tamogatott.
echo       A program Python 3.8+ es numpy alatt fut, ezek XP-n nem
echo       telepithetok. Hasznalj Windows 7 / 10 / 11 vagy Mac gepet.
goto :fail

:fail
echo.
pause
exit /b 1
