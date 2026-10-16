#!/usr/bin/env bash
# Build in an isolated Linux directory. Never installs, flashes or reboots.
set -Eeuo pipefail
sdk=${1:?Usage: build_candidate.sh SDK_ARCHIVE WORK_DIRECTORY [--image]}
work=${2:?Provide a new absolute work directory}
mode=${3:---object-only}
[[ "$work" = /* && "$work" != / && "$work" != /boot && "$work" != /usr ]] || exit 2
[[ "$mode" == --object-only || "$mode" == --image ]] || exit 2
here=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
mkdir -p "$work"
if [[ ! -d "$work/kernel" ]]; then
    tar -xf "$sdk" -C "$work" --strip-components=1 evm3588_linux_v1.0.3/kernel
fi
cd "$work/kernel"
source_state=$(python3 - "$here/candidate.json" <<'PY'
import hashlib,json,pathlib,sys
m=json.load(open(sys.argv[1]))
p=pathlib.Path('drivers/media/i2c/imx415.c')
digest=hashlib.sha256(p.read_bytes()).hexdigest()
if digest==m['sourceSha256']: print('pristine')
elif digest==m['candidateSourceSha256']: print('patched')
else: raise SystemExit('BSP driver checksum mismatch; use a fresh work directory')
PY
)
if [[ "$source_state" == pristine ]]; then
    git apply --check "$here/0001-experimental-mode.patch"
    git apply "$here/0001-experimental-mode.patch"
else
    git apply --reverse --check "$here/0001-experimental-mode.patch"
fi
export ARCH=arm64 CROSS_COMPILE=${CROSS_COMPILE:-aarch64-linux-gnu-}
if [[ -n ${LIVE_CONFIG:-} ]]; then
    mkdir -p "$work/out"
    cp "$LIVE_CONFIG" "$work/out/.config"
    make O="$work/out" olddefconfig
else
    make O="$work/out" rockchip_linux_defconfig rk3588_linux.config evm3588.config
fi
make O="$work/out" -j4 drivers/media/i2c/imx415.o
if [[ "$mode" == --image ]]; then
    # Reference SDK image only: current board config/DTB must be compared separately.
    cp "$here/evm3588-b1-4k60.dts" arch/arm64/boot/dts/rockchip/evm3588-b1-4k60.dts
    make O="$work/out" -j4 Image rockchip/evm3588-b1-4k60.dtb
fi
sha256sum "$work/out/drivers/media/i2c/imx415.o" > "$work/object.sha256"
printf '%s\n' 'Candidate compiled. No board changes. NOT an approved boot image.'
