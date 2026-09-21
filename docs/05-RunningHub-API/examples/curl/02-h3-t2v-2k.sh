#!/usr/bin/env bash
# 2K直出；默认dry-run。--execute后预估成功才提交；taskId立即持久化。
# 不额外虚构768P生成费。超时只能resume，不重提。
set -euo pipefail
HERE="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
exec python3 "$HERE/../python/rh_min_client.py" video \
  --key-type enterprise-shared --resolution 2K \
  --duration "${DURATION:-5}" --prompt "${PROMPT:-一只橙猫在雨后屋顶缓慢行走}" "$@"
