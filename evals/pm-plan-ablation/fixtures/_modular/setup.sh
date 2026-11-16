#!/usr/bin/env bash
# Prepares a modular snapshot the way a working developer clone is set up.
# Old LLVM pins can no longer be fetched (GitHub's tarball checksum drifted),
# so reuse the LLVM source already fetched for the source clone.
# Env: EVAL_SOURCE (the source clone). Runs in the workspace root.
set -euo pipefail

output_base="$HOME/.cache/bazel/_bazel_$USER/$(printf %s "$EVAL_SOURCE" | md5sum | cut -c1-32)"
llvm="$(readlink -f "$output_base/external/+llvm_source+llvm-raw")"
if [[ ! -f "$llvm/llvm/CMakeLists.txt" ]]; then
  echo "setup: no fetched LLVM source under $output_base; build once in $EVAL_SOURCE first" >&2
  exit 1
fi

cat >local.bazelrc <<EOF
common --config=prebuilt-mojo
common --override_repository=llvm-raw=$llvm
EOF

# The wrapper's first call in a fresh tree only bootstraps itself and exits 1.
./bazelw info release >/dev/null 2>&1 || true
./bazelw info release >/dev/null 2>&1
