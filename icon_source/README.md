# App icon

`icon.png` (1024x1024) is the source artwork. `app.spec` points PyInstaller at
`icon_source/icon.icns`, which isn't committed - macOS's `.icns` format has to
be built with `sips`/`iconutil`, which only exist on a Mac (not available in
the Linux dev sandbox this repo is otherwise built in).

## Generate icon.icns (run on your Mac, from the repo root)

```bash
cd icon_source
mkdir icon.iconset
for size in 16 32 128 256 512; do
  sips -z $size $size icon.png --out icon.iconset/icon_${size}x${size}.png
  double=$((size * 2))
  sips -z $double $double icon.png --out icon.iconset/icon_${size}x${size}@2x.png
done
iconutil -c icns icon.iconset -o icon.icns
rm -rf icon.iconset
```

Then rebuild the app: `./build_app.sh` (from the repo root). The new icon
should show up on `dist/Stock Lookup.app` - if Finder/Dock still show the old
one, that's icon caching; relaunching Finder (`killall Finder`) or logging out
and back in clears it.
