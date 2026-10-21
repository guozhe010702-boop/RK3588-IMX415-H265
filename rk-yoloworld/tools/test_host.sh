#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
build=build/host
flags=''
link_flags=''
if [[ "${1:-}" == --sanitize ]]; then
  build=build/asan
  flags='-fsanitize=address,undefined -fno-omit-frame-pointer -fno-pie'
  link_flags='-no-pie'
fi
cmake -S . -B "$build" -DCORE_ONLY=ON -DADAPTER_TESTS=ON -DCMAKE_BUILD_TYPE=Debug \
  -DCMAKE_CXX_FLAGS="$flags" -DCMAKE_EXE_LINKER_FLAGS="$link_flags" -DCMAKE_CXX_FLAGS_DEBUG='-O1 -g'
cmake --build "$build" -j4
# GCC 9 LeakSanitizer's signal handler is unreliable in this Docker environment.
# Address/UB instrumentation stays enabled; model/resource lifetimes also have
# explicit tests and real-board RSS measurements.
ASAN_OPTIONS=detect_leaks=0:handle_segv=0 ctest --test-dir "$build" --output-on-failure --timeout 60
