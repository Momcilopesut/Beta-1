#!/usr/bin/env bash
# Builds "Stock Lookup.app", a double-clickable Mac app bundle - run this
# on a Mac, from the project folder, with the venv activated:
#
#   ./build_app.sh
#
# The result lands at dist/Stock Lookup.app - drag it into /Applications,
# or just double-click it where it is. Since it isn't signed by Apple,
# the FIRST launch will be blocked by Gatekeeper; right-click the app ->
# Open (not a plain double-click) once to approve it, or approve it in
# System Settings -> Privacy & Security -> "Open Anyway" if that option
# shows up there instead. After that one-time approval, double-clicking
# works normally.
set -euo pipefail
cd "$(dirname "$0")"

pip install -r requirements-dev.txt
rm -rf build dist
pyinstaller app.spec

echo
echo "Built: $(pwd)/dist/Stock Lookup.app"
echo "Drag it into /Applications, or double-click it where it is."
echo "First launch: right-click the app -> Open (Gatekeeper will warn since it's unsigned)."
