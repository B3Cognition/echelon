#!/usr/bin/env bash
set -euo pipefail

if [[ $# -lt 1 ]]; then
  echo "usage: $0 <count> <command...>" >&2
  exit 64
fi

count="$1"
shift

if [[ "$count" -lt 1 ]]; then
  echo "count must be >= 1" >&2
  exit 64
fi

if [[ $# -lt 1 ]]; then
  echo "usage: $0 <count> <command...>" >&2
  exit 64
fi

hold="${LOCK_HOLD_SECONDS:-0}"
barrier_dir="$(mktemp -d)"
ready_dir="$barrier_dir/ready"
release_file="$barrier_dir/release"
mkdir -p "$ready_dir"

pids=()

for i in $(seq 1 "$count"); do
  (
    touch "$ready_dir/$i"
    while [[ ! -f "$release_file" ]]; do sleep 0.01; done
    "$@"
    if [[ "$hold" != "0" ]]; then
      sleep "$hold"
    fi
  ) &
  pids+=("$!")
done

while true; do
  ready_count="$(find "$ready_dir" -type f | wc -l | tr -d ' ')"
  if [[ "$ready_count" -ge "$count" ]]; then
    break
  fi
  sleep 0.01
done

: > "$release_file"

status=0
for pid in "${pids[@]}"; do
  if ! wait "$pid"; then
    status=1
  fi
done

rm -rf "$barrier_dir"
exit "$status"
