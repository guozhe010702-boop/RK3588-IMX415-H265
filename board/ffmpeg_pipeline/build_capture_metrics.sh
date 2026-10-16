#!/usr/bin/env bash
# Incremental private FFmpeg rebuild. Does not restart services or touch /usr.
set -Eeuo pipefail
root=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
build="$root/build/ffmpeg"
[[ -f "$build/ffbuild/config.mak" ]] || { echo 'Run build_runtime.sh first'; exit 1; }
exec 9>"$root/build/build.lock"
flock -n 9 || { echo 'Another runtime build is running'; exit 1; }
export LD_LIBRARY_PATH="$root/runtime/lib:$root/runtime/lib64:${LD_LIBRARY_PATH:-}"
# A trailing ':' in the vendor C_INCLUDE_PATH makes '.' a system include,
# causing GCC to move it behind installed FFmpeg headers despite an early -I.
unset CPATH C_INCLUDE_PATH CPLUS_INCLUDE_PATH OBJC_INCLUDE_PATH
cd "$build"
patch="$root/patches/0002-capture-metrics.patch"
if git apply --check "$patch"; then
    git apply "$patch"
else
    git apply --reverse --check "$patch"
fi
# Installed public FFmpeg headers share this private prefix with MPP/RGA.
# Always prefer matching source headers when rebuilding internal translation units.
configured_cflags=$(sed -n 's/^CFLAGS=//p' ffbuild/config.mak)
make -j4 V=1 CFLAGS="-I. $configured_cflags" ffmpeg ffprobe
./ffmpeg -hide_banner -encoders 2>/dev/null | grep hevc_rkmpp
for name in ffmpeg ffprobe; do
    install -m 755 "$name" "$root/runtime/bin/$name.metrics-new"
    mv "$root/runtime/bin/$name.metrics-new" "$root/runtime/bin/$name"
done
python3 - "$root" <<'PY'
import datetime,hashlib,json,pathlib,sys
root=pathlib.Path(sys.argv[1]); path=root/'runtime/build-manifest.json'
m=json.loads(path.read_text()) if path.exists() else {}
m['captureMetricsBuiltAt']=datetime.datetime.now().astimezone().isoformat()
hashes=m.setdefault('sha256',{})
for p in [root/'runtime/bin/ffmpeg',root/'runtime/bin/ffprobe',root/'patches/0002-capture-metrics.patch']:
    hashes[str(p.relative_to(root))]=hashlib.sha256(p.read_bytes()).hexdigest()
path.write_text(json.dumps(m,indent=2)+'\n')
PY
