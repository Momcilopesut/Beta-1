# -*- mode: python ; coding: utf-8 -*-
# PyInstaller spec for the double-clickable "Stock Lookup.app" bundle.
# Build with: pyinstaller app.spec (see build_app.sh / README's "Package
# as a Mac app" section). Must be built on a Mac - this produces a
# macOS-specific .app bundle, not a cross-platform artifact.

a = Analysis(
    ["app.py"],
    pathex=[],
    binaries=[],
    # templates/ and static/ aren't Python code, so PyInstaller won't
    # pick them up on its own - app.py looks for them under sys._MEIPASS
    # at runtime specifically because of this.
    datas=[("templates", "templates"), ("static", "static")],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="Stock Lookup",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,  # no terminal window - this is the double-click-to-launch behavior
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="Stock Lookup",
)

app = BUNDLE(
    coll,
    name="Stock Lookup.app",
    # Built from icon_source/icon.png - see icon_source/README.md for how
    # to (re)generate icon_source/icon.icns on a Mac (sips/iconutil aren't
    # available in this Linux dev sandbox, so that conversion step has to
    # happen on your own machine).
    icon="icon_source/icon.icns",
    bundle_identifier=None,
)
