#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
ROOT=$PWD
PREFIX=${CROSS_PREFIX:-/usr/bin/aarch64-linux-gnu-}
export CC=${PREFIX}gcc CXX=${PREFIX}g++
test -x "$CC"
python3 tools/verify_sources.py
TAG=$($CC -dumpversion | cut -d. -f1)
MUXER="$ROOT/build/muxer-gcc$TAG"
ARM_BUILD="$ROOT/build/arm64-gcc$TAG"
mkdir -p build dist/lib
if [[ ! -s vendor/librga.so ]]; then
  cmake -S build/rga-source -B "build/rga-gcc$TAG" -DCMAKE_SYSTEM_NAME=Linux -DCMAKE_BUILD_TARGET=cmake_linux -DBUILD_WITH_VERSION=true \
    -DCMAKE_C_COMPILER="$CC" -DCMAKE_CXX_COMPILER="$CXX"
  cmake --build "build/rga-gcc$TAG" --target rga -j4
  cp -L "build/rga-gcc$TAG/librga.so" vendor/librga.so
fi
if [[ ! -f "$MUXER/lib/libavformat.so" ]]; then
  mkdir -p "build/ffmpeg-gcc$TAG"
  tar -xf vendor/ffmpeg-7.1.1.tar.xz -C "build/ffmpeg-gcc$TAG" --strip-components=1
  pushd "build/ffmpeg-gcc$TAG" >/dev/null
  ./configure --prefix="$MUXER" --arch=aarch64 --target-os=linux --enable-cross-compile --cross-prefix="$PREFIX" \
    --disable-everything --disable-autodetect --disable-programs --disable-doc --disable-network --disable-debug \
    --disable-avdevice --disable-avfilter --disable-swscale --disable-swresample --enable-muxer=nut \
    --enable-encoder=rawvideo --enable-shared --disable-static >../muxer-configure.log
  make -j4 >../muxer-build.log 2>&1
  make install >../muxer-install.log 2>&1
  popd >/dev/null
fi
cmake -S . -B "$ARM_BUILD" -DMUXER_PREFIX="$MUXER" -DCMAKE_SYSTEM_NAME=Linux -DCMAKE_SYSTEM_PROCESSOR=aarch64 -DCMAKE_C_COMPILER="$CC" -DCMAKE_CXX_COMPILER="$CXX" -DCMAKE_BUILD_TYPE=Release \
  -DCMAKE_C_FLAGS_RELEASE="-O3 -DNDEBUG" -DCMAKE_CXX_FLAGS_RELEASE="-O3 -DNDEBUG"
cmake --build "$ARM_BUILD" -j4
cp "$ARM_BUILD/rknn_yolo_world_realtime" dist/
cp -L "$MUXER"/lib/libav{format,codec,util}.so* dist/lib/
cp vendor/librga.so dist/lib/librga.so.2
# Upstream CMake uses SONAME 1; the board's Meson package uses SONAME 2.
# Keep aliases to the SAME private ELF, never load two different RGA versions.
cp vendor/librga.so dist/lib/librga.so
cp vendor/librga.so dist/lib/librga.so.1
cp run_realtime_yolo_world.sh config.env dist/
python3 tools/record_build.py
echo 'ARM64 build complete; models and librknnrt must be supplied and probed before use.'
