#!/usr/bin/env bash
# Native ARM64 build. Vendor runtimes and the live camera are untouched.
set -Eeuo pipefail
root=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
prefix="$root/runtime"
build="$root/build"
mkdir -p "$build" "$prefix/bin"
exec 9>"$build/build.lock"
flock -n 9 || { echo 'Another runtime build is running'; exit 1; }
trap 'result=$?; printf "{\"exitCode\":%d,\"finishedAt\":\"%s\"}\n" "$result" "$(date -Is)" > "$build/result.json"' EXIT
rm -f "$build/result.json"
[[ $(uname -m) == aarch64 ]] || { echo 'Build on the ARM64 board'; exit 1; }

if [[ ${1:-} == --install-build-deps ]]; then
  # --no-upgrade preserves installed runtime packages.
  DEBIAN_FRONTEND=noninteractive apt-get install -y --no-upgrade --no-install-recommends cmake meson ninja-build libdrm-dev
elif [[ -n ${1:-} ]]; then
  echo 'Usage: bash build_runtime.sh [--install-build-deps]'; exit 2
fi
for tool in git cmake meson ninja gcc pkg-config curl; do
  command -v "$tool" >/dev/null || { echo "Missing build dependency: $tool"; exit 1; }
done

checkout() {
  local component=$1 url branch commit directory
  readarray -t values < <(python3 - "$root/versions.json" "$component" <<'PY'
import json,sys
item=json.load(open(sys.argv[1]))[sys.argv[2]]
for key in ('url','branch','commit'): print(item[key])
PY
  )
  url=${values[0]}; branch=${values[1]}; commit=${values[2]}
  directory="$build/$component"
  if [[ ! -d "$directory/.git" ]]; then
    git clone --depth 1 --branch "$branch" "$url" "$directory"
  fi
  if ! git -C "$directory" cat-file -e "$commit^{commit}" 2>/dev/null; then
    git -C "$directory" fetch --depth 1 origin "$commit"
  fi
  git -C "$directory" checkout --detach "$commit"
  [[ $(git -C "$directory" rev-parse HEAD) == "$commit" ]]
}

echo 'PHASE: fetch pinned sources'
checkout mpp
checkout rga
checkout ffmpeg
echo 'PHASE: private MPP'
cmake -S "$build/mpp" -B "$build/mpp-build" -DCMAKE_INSTALL_PREFIX="$prefix" -DCMAKE_BUILD_TYPE=Release -DBUILD_SHARED_LIBS=ON -DBUILD_TEST=OFF
cmake --build "$build/mpp-build" -j4
cmake --install "$build/mpp-build"
echo 'PHASE: private RGA'
if [[ ! -f "$build/rga-build/build.ninja" ]]; then
  meson setup "$build/rga-build" "$build/rga" --prefix="$prefix" --libdir=lib --buildtype=release --default-library=shared -Dcpp_args=-fpermissive -Dlibdrm=false -Dlibrga_demo=false
fi
ninja -C "$build/rga-build" -j4
ninja -C "$build/rga-build" install
echo 'PHASE: patched FFmpeg'
cd "$build/ffmpeg"
if git apply --check "$root/patches/0001-nv12m-capture.patch"; then
  git apply "$root/patches/0001-nv12m-capture.patch"
else
  git apply --reverse --check "$root/patches/0001-nv12m-capture.patch"
fi
export PKG_CONFIG_PATH="$prefix/lib/pkgconfig:$prefix/lib64/pkgconfig:${PKG_CONFIG_PATH:-}"
export LD_LIBRARY_PATH="$prefix/lib:$prefix/lib64:${LD_LIBRARY_PATH:-}"
./configure --prefix="$prefix" --disable-autodetect --disable-doc --disable-debug --disable-ffplay --enable-version3 --enable-libdrm --enable-rkmpp --enable-rkrga --extra-cflags="-I$prefix/include" --extra-ldflags="-L$prefix/lib -Wl,-rpath,$prefix/lib"
make -j4
make install
echo 'PHASE: MediaMTX'
readarray -t media < <(python3 - "$root/versions.json" <<'PY'
import json,sys
item=json.load(open(sys.argv[1]))['mediamtx']
print(item['url']); print(item['sha256'])
PY
)
archive="$build/mediamtx.tar.gz"
if [[ ! -f "$archive" ]]; then curl -fL --retry 3 "${media[0]}" -o "$archive"; fi
echo "${media[1]}  $archive" | sha256sum --check
tar -xzf "$archive" -C "$prefix/bin" mediamtx
"$prefix/bin/ffmpeg" -hide_banner -encoders | grep -E '(hevc|h264)_rkmpp'
"$prefix/bin/mediamtx" --version
python3 - "$root" <<'PY'
import hashlib,json,pathlib,subprocess,sys,datetime
root=pathlib.Path(sys.argv[1]); lock=json.loads((root/'versions.json').read_text())
lock['builtAt']=datetime.datetime.now().astimezone().isoformat()
lock['sha256']={str(p.relative_to(root)):hashlib.sha256(p.read_bytes()).hexdigest() for p in [root/'runtime/bin/ffmpeg',root/'runtime/bin/ffprobe',root/'runtime/bin/mediamtx',root/'patches/0001-nv12m-capture.patch']}
lock['configure']=(root/'build/ffmpeg/ffbuild/config.log').read_text(errors='replace').splitlines()[0:10]
(root/'runtime/build-manifest.json').write_text(json.dumps(lock,indent=2)+'\n')
PY
echo 'PHASE: DONE'
