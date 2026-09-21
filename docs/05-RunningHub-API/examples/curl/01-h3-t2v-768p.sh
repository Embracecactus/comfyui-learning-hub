#!/usr/bin/env bash
# 兼容原入口；完整生命周期委托统一客户端。默认dry-run，不联网/扣费。
# 价格取唯一证据数据；414只是历史拒绝，不能推断当前余额或建议充值。
set -euo pipefail
HERE="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
exec python3 "$HERE/../python/rh_min_client.py" video \
  --key-type enterprise-shared --resolution 768P \
  --duration "${DURATION:-5}" --prompt "${PROMPT:-一只橙猫在雨后屋顶缓慢行走}" "$@"
