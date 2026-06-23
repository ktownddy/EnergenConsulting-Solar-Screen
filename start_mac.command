#!/bin/bash
# Energen Solar Deal Snapshot — Mac launcher
# Double-click this file in Finder to launch the app.

set -e
cd "$(dirname "$0")"

echo ""
echo "  Energen Solar Deal Snapshot"
echo "  ----------------------------"
echo ""

PY=""
for cand in python3 python3.11 python3.12 python3.10 /usr/local/bin/python3 /opt/homebrew/bin/python3; do
  if command -v "$cand" >/dev/null 2>&1; then
    PY="$cand"
    break
  fi
done

if [ -z "$PY" ]; then
  echo "Python 3 is not installed on this Mac."
  echo "Easiest fix: open Terminal and run:"
  echo "    xcode-select --install"
  echo "or download from https://www.python.org/downloads/"
  read -p "Press Enter to close..."
  exit 1
fi

VENV=".venv"
if [ ! -d "$VENV" ]; then
  echo "First run: setting up local environment (~1 minute)..."
  "$PY" -m venv "$VENV"
fi
source "$VENV/bin/activate"

NEED_INSTALL=true
if [ -f "$VENV/.requirements_installed" ]; then
  if cmp -s "requirements.txt" "$VENV/.requirements_installed"; then
    NEED_INSTALL=false
  fi
fi
if [ "$NEED_INSTALL" = true ]; then
  echo "Installing dependencies..."
  pip install --upgrade pip --quiet
  pip install -r requirements.txt --quiet
  cp requirements.txt "$VENV/.requirements_installed"
fi

echo ""
echo "Starting the app. Your browser should open automatically."
echo "If not, open: http://localhost:8501"
echo "To stop the app, close this window or press Ctrl+C."
echo ""

streamlit run app.py --browser.gatherUsageStats false
