#!/usr/bin/env python3
"""Read-only RunningHub evidence capture and offline two-stage cost reconciliation.

This module never creates, cancels, retries or regenerates a paid task. Credentials
are read from RH_API_KEY only. Captures are private under output/; publishing a
capture requires reviewing/redacting prompts and account data as well as tokens.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from urllib.parse import urlsplit

from rh_min_client import RunningHubClient, RHError, redact

H3 = 'minimax/hailuo-h3/text-to-video'
REGEN = 'minimax/hailuo-h3/regeneration-text-to-video'
DEFAULT_OUT = Path('output/runninghub/api/evidence-audit.json')


def digest(text: str) -> str:
    return hashlib.sha256(text.encode('utf-8')).hexdigest()


def file_hash(path: Path) -> str:
    value = hashlib.sha256()
    with path.open('rb') as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b''):
            value.update(chunk)
    return value.hexdigest()


def safe_capture(value: object, key: str = '') -> object:
    """No signed media URLs, prompt bodies, credentials or balances in shareable capture."""
    value = redact(value, key)
    if isinstance(value, dict):
        out = {}
        for k,v in value.items():
            lower=k.lower()
            if lower in ('prompt','final_model_prompt'):
                out[k+'_sha256']=digest(str(v))
            elif lower in ('remaincoins','remainmoney','balance','balancecny','userbalance'):
                out[k]='[PRIVATE_BALANCE_OMITTED]'
            else:
                out[k]=safe_capture(v,key)
        return out
    if isinstance(value,list):
        return [safe_capture(v,key) for v in value]
    if isinstance(value,str) and value.startswith(('https://','http://')):
        u=urlsplit(value)
        return {'url_sha256':digest(value),'host':u.hostname,'note':'Private URL omitted'}
    return value


def capture(task_ids:list[str], plan:list[dict], client:RunningHubClient) -> tuple[dict,int]:
    result={'captured_at':datetime.now(timezone.utc).isoformat(timespec='seconds'),
            'creates_paid_tasks':False,'tasks':[],'quotes':[],'status':'complete'}
    if not client.key:
        result.update(status='blocked_missing_key', reason='RH_API_KEY not available; no requests sent')
        return result,2
    for task_id in dict.fromkeys(task_ids):
        item={'task_id':task_id}
        try:
            item['response']=safe_capture(client.query(task_id),client.key)
            item['status']='read_success'
        except (RHError,OSError,ValueError) as exc:
            item.update(status='read_failed',error=str(redact(str(exc),client.key)))
            result['status']='partial'
        result['tasks'].append(item)
    for request in plan:
        endpoint,payload=request['endpoint'],request['payload']
        item={'endpoint':endpoint,'request':safe_capture(payload,client.key),
              'request_sha256':digest(json.dumps(payload,ensure_ascii=False,sort_keys=True))}
        if endpoint==REGEN and (not payload.get('baseVideoUrl') or not request.get('source_validation_passed')):
            item.update(status='blocked_missing_validated_source', reason='Use source-check before quoting regeneration; never invent a video URL')
            result['status']='partial'
        else:
            try:
                quote=client.price_preview(endpoint,payload)
                if quote.get('estimatedPrice') is None or not quote.get('currency'):
                    raise RHError('Missing estimatedPrice/currency; not a zero quote')
                item.update(status='quoted_not_billed',response=safe_capture(quote,client.key))
            except (RHError,OSError,ValueError) as exc:
                item.update(status='quote_failed',error=str(redact(str(exc),client.key)))
                result['status']='partial'
        result['quotes'].append(item)
    return result,0 if result['status']=='complete' else 2


def probe_source(path:Path) -> dict:
    raw=subprocess.run(['ffprobe','-v','error','-count_frames','-show_entries',
        'format=format_name,duration:stream=codec_type,width,height,avg_frame_rate,nb_read_frames',
        '-of','json',str(path)],capture_output=True,text=True,check=True).stdout
    data=json.loads(raw)
    video=next((x for x in data.get('streams',[]) if x.get('codec_type')=='video'),{})
    a,b=str(video.get('avg_frame_rate','0/1')).split('/')
    fps=Decimal(a)/Decimal(b) if Decimal(b) else Decimal(0)
    return {'width':video.get('width'),'height':video.get('height'),'fps':str(fps),
            'frames':int(video.get('nb_read_frames',0)),
            'has_audio':any(x.get('codec_type')=='audio' for x in data.get('streams',[])),
            'format_name':data.get('format',{}).get('format_name',''),
            'duration_seconds':data.get('format',{}).get('duration')}


def validate_source(media:dict, source_record:dict, final_prompt:str) -> dict:
    errors=[]
    w,h=media.get('width') or 0,media.get('height') or 0
    if w<=0 or h<=0 or w%32 or h%32 or w*h>768*1344:
        errors.append('source dimensions must be positive, divisible by 32, area <= 768*1344')
    if Decimal(str(media.get('fps',0)))!=Decimal(24):
        errors.append('source fps must equal 24')
    if not media.get('has_audio'):
        errors.append('source must contain an audio stream')
    if not 107<=int(media.get('frames',0))<=362:
        errors.append('source frame count must be 107..362')
    if 'mp4' not in media.get('format_name','').split(','):
        errors.append('source must be an MP4 container')
    if not source_record.get('task_id'):
        errors.append('missing source task ID')
    if source_record.get('endpoint')!=H3:
        errors.append('source must be a verified H3 text-to-video chain; open-workflow equivalence is unverified')
    known=source_record.get('final_model_prompt')
    if not known or known!=final_prompt:
        errors.append('missing/mismatched actual final model prompt; original user prompt is not a substitute')
    if source_record.get('status') not in ('SUCCESS','MEDIA_VALIDATED'):
        errors.append('source task has not succeeded')
    return {'status':'passed' if not errors else 'blocked','errors':errors,
            'source_task_id':source_record.get('task_id'),'final_prompt_sha256':digest(final_prompt),
            'media':media,'note':'Local constraint checks only; does not prove the platform accepts this source or price.'}


def reconcile(stage_a:dict, stage_b:dict) -> dict:
    """Sum only explicitly disjoint billing components. Unknown fields stay unknown.

Input contract is documented in 04-接入与费用验收.md. Each charge_id must come from
an identified billing scope; arbitrary parent/child aggregate totals are rejected.
"""
    errors=[]
    if not stage_a.get('task_id') or not stage_b.get('task_id') or stage_a.get('task_id')==stage_b.get('task_id'):
        errors.append('two distinct task IDs are required')
    if stage_b.get('source_task_id')!=stage_a.get('task_id'):
        errors.append('stage B is not linked to stage A')
    prompt=stage_a.get('final_prompt_sha256')
    if not prompt or stage_b.get('final_prompt_sha256')!=prompt:
        errors.append('final model prompt hashes do not match')
    if not stage_a.get('output_sha256') or stage_b.get('source_sha256')!=stage_a.get('output_sha256'):
        errors.append('stage B source media is not verified as stage A output')
    if stage_a.get('endpoint')!=H3 or stage_b.get('endpoint')!=REGEN:
        errors.append('unexpected stage endpoints')
    charges={}
    totals={'CNY':Decimal(0),'RH_coin':Decimal(0)}
    for stage in (stage_a,stage_b):
        if stage.get('status')!='SUCCESS':
            errors.append('stage has no successful final status; failed task costs need separate accounting')
        if stage.get('billing_complete') is not True:
            errors.append('stage billing completeness not established')
        if not isinstance(stage.get('cost_components'),list) or not stage['cost_components']:
            errors.append('stage has no explicit billing components')
        for row in stage.get('cost_components') or []:
            if row.get('scope')!='disjoint_charge' or not row.get('charge_id') or not row.get('source_field'):
                errors.append('unknown/overlapping billing scope; do not sum parent or chain aggregates')
                continue
            unit=row.get('unit')
            amount=row.get('amount')
            try:
                value=Decimal(str(amount))
                if not value.is_finite() or value<0:
                    raise ValueError('amount must be finite and nonnegative')
            except (InvalidOperation,ValueError):
                errors.append('unknown/invalid charge amount; null is not zero')
                continue
            if unit not in totals:
                errors.append('unknown billing unit')
                continue
            key=row['charge_id']
            pair=(unit,value)
            if key in charges and charges[key]!=pair:
                errors.append('conflicting duplicate charge ID')
            elif key not in charges:
                charges[key]=pair
                totals[unit]+=value
    return {'status':'reconciled' if not errors else 'incomplete',
            'task_ids':[stage_a.get('task_id'),stage_b.get('task_id')],
            'known_components':{k:str(v) for k,v in totals.items()},
            'complete_totals':{k:str(v) for k,v in totals.items()} if not errors else None,
            'total_cny_including_coins':str(totals['CNY']) if not errors and not totals['RH_coin'] else None,
            'errors':list(dict.fromkeys(errors)), 'new_paid_tasks':0,
            'verification_level':'supplied_scope_and_arithmetic_only; not independent bill authentication'}


def save(path:Path,result:dict) -> None:
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    try: path.chmod(0o600)
    except OSError: pass


def main(argv:list[str]|None=None)->int:
    ap=argparse.ArgumentParser(description=__doc__)
    sub=ap.add_subparsers(dest='cmd',required=True)
    p=sub.add_parser('collect',help='Read-only query/price capture; never submits tasks')
    p.add_argument('--task-id',action='append',default=[])
    p.add_argument('--plan',type=Path,help='JSON list of exact endpoint/payload quote requests')
    p.add_argument('--out',type=Path,default=DEFAULT_OUT)
    p=sub.add_parser('source-check')
    p.add_argument('--video',type=Path,required=True)
    p.add_argument('--source-record',type=Path,required=True)
    p.add_argument('--final-prompt-file',type=Path,required=True)
    p.add_argument('--out',type=Path,default=DEFAULT_OUT)
    p=sub.add_parser('reconcile')
    p.add_argument('--stage-a',type=Path,required=True)
    p.add_argument('--stage-b',type=Path,required=True)
    p.add_argument('--out',type=Path,default=DEFAULT_OUT)
    args=ap.parse_args(argv)
    if args.cmd=='collect':
        plan=json.loads(args.plan.read_text()) if args.plan else []
        result,code=capture(args.task_id,plan,RunningHubClient())
    elif args.cmd=='source-check':
        prompt=args.final_prompt_file.read_text(encoding='utf-8')
        # Do not strip whitespace: the final prompt must match exactly.
        result=validate_source(probe_source(args.video),json.loads(args.source_record.read_text()),prompt)
        result['source_sha256']=file_hash(args.video)
        code=0 if result['status']=='passed' else 2
    else:
        result=reconcile(json.loads(args.stage_a.read_text()),json.loads(args.stage_b.read_text()))
        code=0 if result['status']=='reconciled' else 2
    save(args.out,result)
    print(json.dumps({'status':result['status'],'record':str(args.out),'creates_paid_tasks':False},ensure_ascii=False))
    return code


if __name__=='__main__':
    try:
        raise SystemExit(main())
    except (RHError,ValueError,OSError,subprocess.CalledProcessError) as exc:
        print(str(redact(str(exc),os.environ.get('RH_API_KEY',''))),file=sys.stderr)
        raise SystemExit(2)
