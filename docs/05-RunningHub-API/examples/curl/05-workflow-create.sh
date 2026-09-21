#!/usr/bin/env bash
# 已提交的云端开源H3 768P工作流；不是标准模型档位价格证据。
# 默认dry-run；只有--execute创建任务，实例运行币随实际用量变化。
set -euo pipefail
HERE="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
exec python3 "$HERE/../python/rh_min_client.py" run-workflow - \
  --inline "$HERE/../workflows/h3-t2v-open-768p-cloud.json" --instance-type plus "$@"
