#!/usr/bin/env bash
# 标准H3文生再生成；来源与最终模型提示词必须先校验，禁止占位源URL。
# Usage: bash 03-h3-regen-768p-to-2k.sh source.mp4 source-record.json final-prompt.txt [--execute]
# 默认dry-run；仅--execute上传→有效预估→单次提交，不自动重试生成。
set -euo pipefail
HERE="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
export PYTHONPATH="$HERE/../python${PYTHONPATH:+:$PYTHONPATH}"
exec python3 - "$@" <<'PY'
import argparse, json, os, sys, subprocess
from pathlib import Path
from rh_min_client import RunningHubClient, RHError, redact
from rh_evidence_audit import probe_source, validate_source, file_hash, REGEN
p=argparse.ArgumentParser()
p.add_argument('video',type=Path); p.add_argument('source_record',type=Path)
p.add_argument('final_prompt_file',type=Path); p.add_argument('--execute',action='store_true')
a=p.parse_args()
try:
    source=json.loads(a.source_record.read_text(encoding='utf-8'))
    prompt=a.final_prompt_file.read_text(encoding='utf-8')
    validation=validate_source(probe_source(a.video),source,prompt)
    if validation['status']!='passed':
        raise RHError('Source rejected: '+'; '.join(validation['errors']))
    # This linkage is local evidence, not proof of platform acceptance.
    payload={'prompt':prompt,'resolution':'2K','baseVideoUrl':''}
    result=RunningHubClient().run(REGEN,payload,local_files={'baseVideoUrl':str(a.video)},execute=a.execute,
        source_chain={'source_task_id':source['task_id'],'source_sha256':file_hash(a.video),
                      'final_prompt_sha256':validation['final_prompt_sha256']})
    print(json.dumps({'source_task_id':source['task_id'],
                      'final_prompt_sha256':validation['final_prompt_sha256'],
                      'regeneration_task_id':result.get('task_id'),'status':result['status']},ensure_ascii=False))
except (RHError,ValueError,OSError,subprocess.CalledProcessError) as e:
    print(str(redact(str(e),os.environ.get('RH_API_KEY',''))),file=sys.stderr)
    sys.exit(2)
PY
