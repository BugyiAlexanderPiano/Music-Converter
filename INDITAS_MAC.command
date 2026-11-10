#!/bin/bash
# ==================================================================
#  AuraWave Genos Studio Pro - inditas macOS-en
#  Dupla kattintassal inditsd. Ha a Mac nem engedi:
#  jobb klikk -> Megnyitas -> Megnyitas.
# ==================================================================
cd "$(dirname "$0")" || exit 1
clear
echo ""
echo "  ==============================================="
echo "     AuraWave Genos Studio Pro - inditas"
echo "  ==============================================="
echo ""

fail() {
    echo ""
    echo "  $1"
    echo ""
    read -r -p "  Nyomj Entert a bezarashoz..." _
    exit 1
}

# ---- Python keresese (a python.org-os es Homebrew-s Python elonyben,
#      mert az Apple-fele /usr/bin/python3 Tk-ja regi es hibas) --------
PY=""
for cand in \
    /Library/Frameworks/Python.framework/Versions/Current/bin/python3 \
    /opt/homebrew/bin/python3 /usr/local/bin/python3 python3; do
    if command -v "$cand" >/dev/null 2>&1; then
        if "$cand" -c "import sys, tkinter; sys.exit(0 if sys.version_info>=(3,8) and tkinter.TkVersion>=8.6 else 1)" >/dev/null 2>&1; then
            PY="$cand"; break
        fi
    fi
done

if [ -z "$PY" ]; then
    echo "  [!] Nem talalhato megfelelo Python (3.8+ es Tk 8.6)."
    echo "      Megnyitom a letoltesi oldalt: telepitsd a python.org-os"
    echo "      macOS installert, majd inditsd ujra ezt a fajlt."
    open "https://www.python.org/downloads/macos/"
    fail "Telepites utan inditsd ujra az INDITAS_MAC.command fajlt."
fi
echo "  $("$PY" --version) talalhato: $PY"

# ---- Sajat kornyezet a csomagoknak (.venv) -----------------------------
if [ ! -x ".venv/bin/python" ]; then
    echo "  Elso inditas: kornyezet letrehozasa..."
    "$PY" -m venv .venv || fail "[!] Nem sikerult letrehozni a .venv kornyezetet."
fi
VPY=".venv/bin/python"
if ! "$VPY" -c "import numpy" >/dev/null 2>&1; then
    echo "  Elso inditas: a szukseges csomag (numpy) telepitese..."
    "$VPY" -m pip install --upgrade pip >/dev/null 2>&1
    "$VPY" -m pip install -r requirements.txt || fail "[!] A numpy telepitese nem sikerult. Van internet?"
fi

echo "  Program inditasa..."
"$VPY" main.py || fail "[!] A program hibaval allt le (lasd fent)."
