#!/usr/bin/env bash
# Build Linux_Defender-<version>-x86_64.AppImage on Ubuntu 24.04 (x86_64).
# The AppImage bundles Qt 6 (PySide6) and ClamAV; it uses the system Python 3.12.
# Needs: apt (for downloading .deb packages), python3-pip, gcc, curl, internet access.
set -euo pipefail
SRC="$(cd "$(dirname "$0")/.." && pwd)"
VERSION="$(python3 -c "import sys; sys.path.insert(0,'$SRC'); import linux_defender; print(linux_defender.VERSION)")"
WORK="${WORK:-$SRC/build}"
OUT="${OUT:-$SRC/dist}"
PYSIDE_VERSION="${PYSIDE_VERSION:-6.8.1}"
APPDIR="$WORK/AppDir"
DEBS="$WORK/debs"
rm -rf "$APPDIR"; mkdir -p "$APPDIR" "$DEBS" "$OUT"

echo ">> downloading Ubuntu 24.04 packages (clamav, xcb helpers)"
PKGS="clamav clamav-daemon clamav-freshclam libclamav12 libmspack0t64 libjson-c5
      libcurl4t64 libnghttp2-14 librtmp1 libssh-4 libpsl5t64 libbrotli1
      libxcb-cursor0 libxcb-icccm4 libxcb-image0 libxcb-keysyms1 libxcb-render-util0 libxcb-util1 libxkbcommon-x11-0"
( cd "$DEBS" && apt-get download $PKGS )
X="$WORK/extract"; rm -rf "$X"; mkdir -p "$X"
for d in "$DEBS"/*.deb; do dpkg-deb -x "$d" "$X"; done
L="$X/usr/lib/x86_64-linux-gnu"

# Python: Linux Defender runs on Ubuntu 24.04's own /usr/bin/python3.12 (part of every Ubuntu flavour);
# bundling it would push the AppImage past 30 MB.
mkdir -p "$APPDIR/usr/lib"

echo ">> PySide6 $PYSIDE_VERSION"
SP="$APPDIR/usr/lib/linux-defender/site-packages"; mkdir -p "$SP"
WH="$WORK/wheels"; mkdir -p "$WH"
[ -n "$(ls "$WH"/PySide6_Essentials-$PYSIDE_VERSION-* 2>/dev/null)" ] || \
  python3 -m pip download --no-deps -d "$WH" "PySide6-Essentials==$PYSIDE_VERSION" "shiboken6==$PYSIDE_VERSION"
python3 -m pip install --no-deps --no-index --target "$SP" "$WH"/PySide6_Essentials-$PYSIDE_VERSION-*.whl \
  "$WH"/shiboken6-$PYSIDE_VERSION-*.whl -q
Q="$SP/PySide6"
# prune Qt modules Linux Defender does not use
KEEP_LIBS="Core Gui Widgets Network Svg DBus XcbQpa OpenGL"
for f in "$Q"/Qt/lib/libQt6*.so*; do
  n="$(basename "$f" | sed -E 's/^libQt6([A-Za-z0-9]+)\.so.*/\1/')"
  case " $KEEP_LIBS " in *" $n "*) ;; *) rm -f "$f";; esac
done
for m in "$Q"/Qt*.abi3.so "$Q"/Qt*.pyi; do
  n="$(basename "$m" | sed -E 's/\..*//')"
  case "$n" in QtCore|QtGui|QtWidgets|QtNetwork|QtSvg) ;; *) rm -f "$m";; esac
done
rm -f "$Q"/*.pyi "$Q"/libpyside6qml.* "$Q"/Qt/plugins/platforminputcontexts/libqtvirtualkeyboardplugin.so
rm -rf "$Q"/Qt/qml "$Q"/Qt/translations "$Q"/Qt/libexec "$Q"/Qt/metatypes "$Q"/Qt/resources/*.pak \
       "$Q"/include "$Q"/typesystems "$Q"/glue "$Q"/scripts "$Q"/designer "$Q"/assistant "$Q"/linguist \
       "$Q"/lupdate "$Q"/lrelease "$Q"/qmllint "$Q"/qmlformat "$Q"/qmlls "$Q"/qmlcachegen "$Q"/uic "$Q"/rcc \
       "$Q"/Qt/plugins/{designer,qmltooling,sqldrivers,printsupport,egldeviceintegrations,tls,networkinformation,generic} \
       "$Q"/Qt/plugins/wayland-* \
       "$SP"/shiboken6/include "$SP"/*.dist-info/RECORD
find "$Q/Qt/plugins/platforms" -type f ! -name 'libqxcb.so' ! -name 'libqoffscreen.so' -delete
find "$Q/Qt/plugins/imageformats" -type f ! -name 'libqsvg.so' ! -name 'libqico.so' -delete
# Qt's 31 MB ICU data table is replaced by an empty ICU "stubdata" library (see packaging/icustub)
gcc -shared -fPIC -O2 -Wl,-soname,libicudata.so.73 -o "$Q/Qt/lib/libicudata.so.73" "$SRC/packaging/icustub/icudata_stub.c"
find "$SP" -name '__pycache__' -prune -exec rm -rf {} +

echo ">> ClamAV engine"
CA="$APPDIR/usr/clamav"; mkdir -p "$CA/bin" "$CA/sbin" "$CA/lib"
cp -a "$X/usr/sbin/clamd" "$CA/sbin/"
cp -a "$X/usr/bin/freshclam" "$CA/bin/"
for lib in libclamav.so.12* libfreshclam.so.4* libmspack.so.0* libjson-c.so.5* libcurl.so.4* \
           libnghttp2.so.14* librtmp.so.1* libssh.so.4* libpsl.so.5* libbrotlidec.so.1* libbrotlicommon.so.1*; do
  cp -a "$L"/$lib "$CA/lib/" 2>/dev/null || true
done
cp -a "$X/usr/share/doc/clamav/copyright" "$CA/COPYING-clamav" 2>/dev/null || true
# ClamAV 1.5 verifies signature databases with this root certificate. Without it freshclam and clamd fail with
# "Invalid certs directory '/etc/clamav/certs/'" on systems that don't have ClamAV installed.
mkdir -p "$CA/certs"
cp -a "$X/etc/clamav/certs/"*.crt "$CA/certs/"
ls "$CA/certs/"*.crt >/dev/null || { echo "ClamAV root certificate missing" >&2; exit 1; }

echo ">> xcb helper libs for Qt"
mkdir -p "$APPDIR/usr/lib/extra"
for lib in libxcb-cursor.so.0* libxcb-icccm.so.4* libxcb-image.so.0* libxcb-keysyms.so.1* \
           libxcb-render-util.so.0* libxcb-util.so.1* libxkbcommon-x11.so.0*; do
  cp -a "$L"/$lib "$APPDIR/usr/lib/extra/"
done

echo ">> application"
mkdir -p "$APPDIR/usr/lib/linux-defender/app"
cp -a "$SRC/linux_defender" "$APPDIR/usr/lib/linux-defender/app/"
find "$APPDIR/usr/lib/linux-defender/app" -name '__pycache__' -prune -exec rm -rf {} +
cp "$SRC/packaging/launch.py" "$APPDIR/usr/lib/linux-defender/launch.py"
install -m755 "$SRC/packaging/AppRun" "$APPDIR/AppRun"
cp "$SRC/packaging/linux-defender.desktop" "$APPDIR/linux-defender.desktop"
mkdir -p "$APPDIR/usr/share/applications" "$APPDIR/usr/share/icons/hicolor/scalable/apps" "$APPDIR/usr/share/icons/hicolor/256x256/apps"
cp "$SRC/packaging/linux-defender.desktop" "$APPDIR/usr/share/applications/"
cp "$SRC/packaging/linux-defender.png" "$APPDIR/linux-defender.png"
cp "$SRC/packaging/linux-defender.svg" "$APPDIR/usr/share/icons/hicolor/scalable/apps/"
cp "$SRC/packaging/linux-defender.png" "$APPDIR/usr/share/icons/hicolor/256x256/apps/"
ln -sf linux-defender.png "$APPDIR/.DirIcon"
cp "$SRC/LICENSE" "$SRC/README.md" "$APPDIR/usr/lib/linux-defender/"

echo ">> packing"
TOOL="$WORK/appimagetool-x86_64.AppImage"
[ -x "$TOOL" ] || { curl -fsSL -o "$TOOL" https://github.com/AppImage/appimagetool/releases/download/continuous/appimagetool-x86_64.AppImage; chmod +x "$TOOL"; }
ARCH=x86_64 "$TOOL" --appimage-extract-and-run --no-appstream \
  --mksquashfs-opt -b --mksquashfs-opt 1M --mksquashfs-opt -Xcompression-level --mksquashfs-opt 22 \
  "$APPDIR" "$OUT/Linux_Defender-$VERSION-x86_64.AppImage"
echo ">> done: $OUT/Linux_Defender-$VERSION-x86_64.AppImage"
