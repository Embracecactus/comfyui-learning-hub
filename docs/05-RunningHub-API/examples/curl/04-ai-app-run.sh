#!/usr/bin/env bash
# 个人AI应用；默认dry-run。仅显式--execute生成。5s历史用量不外推RH币。
set -euo pipefail
HERE="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
exec python3 "$HERE/../python/rh_min_client.py" video \
  --key-type consumer-member --resolution 2K \
  --duration "${DURATION:-5}" --prompt "${PROMPT:-一只橙猫在雨后屋顶缓慢行走}" "$@"
