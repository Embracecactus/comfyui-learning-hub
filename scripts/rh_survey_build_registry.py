#!/usr/bin/env python3
"""Rebuild offline, or explicitly refresh an official RunningHub model snapshot.

Default uses retained inputs without network access or falsifying freshness.
--refresh downloads the public model registry; prices are only changed with
an explicit --pricing input. No API Key or paid task is used by this builder.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

from rh_survey_handoff import ROOT, DOC, load, outputs, write_outputs

MODELS_URL = 'https://raw.githubusercontent.com/HM-RunningHub/ComfyUI_RH_OpenAPI/main/models_registry.json'


def option_values(model:dict, fields:tuple[str,...])->list[str]:
    for p in model.get('params') or []:
        if p.get('fieldKey') in fields:
            values=[o.get('value') if isinstance(o,dict) else o for o in p.get('options') or []]
            return [str(v) for v in values if v is not None]
    return []


def refresh(registry:dict, raw:bytes, source:str, pricing_raw:bytes|None=None)->dict:
    parsed=json.loads(raw)
    models=parsed.get('models') if isinstance(parsed,dict) else parsed
    if not isinstance(models,list) or not models:
        raise ValueError('Official model snapshot is empty or has an unexpected schema')
    previous={m['id']:m['pricing'] for m in registry['model_capabilities']}
    timestamp=datetime.now(timezone.utc).isoformat(timespec='seconds')
    price_meta=None
    if pricing_raw is not None:
        doc=json.loads(pricing_raw)
        if not isinstance(doc.get('pricing'),list) or not doc['pricing']:
            raise ValueError('Pricing input has no pricing list')
        previous={p['endpoint']:{**p,'status':'official_listed_price',
                                  'snapshot_version':p.get('updated_at') or doc.get('version','unknown')}
                  for p in doc['pricing']}
        price_meta={'sha256':hashlib.sha256(pricing_raw).hexdigest(),'version':doc.get('version'),'imported_at':timestamp}
    capabilities=[]
    for m in models:
        ep=m.get('endpoint')
        if not isinstance(ep,str) or not ep or not isinstance(m.get('params'),list):
            raise ValueError('Model missing endpoint or params; refusing partial publication')
        capabilities.append({'id':ep,'name_cn':m.get('name_cn') or m.get('display_name'),
            'name_en':m.get('name_en'),'class_name':m.get('class_name'),
            'output_type':m.get('output_type'),'category':m.get('category'),
            'method':'POST','path':'/openapi/v2/'+ep,'params':m['params'],
            'resolution_options':option_values(m,('resolution','targetResolution')),
            'duration_options':option_values(m,('duration',)),
            'audio':'See exact parameter contract; not inferred from model family',
            'pricing':previous.get(ep,{'status':'no_public_price','note':'No retained exact-endpoint price'}),
            'verification_status':'schema_verified','verification_notes':[], 'sources':[source]})
    if len({c['id'] for c in capabilities})!=len(capabilities):
        raise ValueError('Duplicate endpoints in model input')
    registry['model_capabilities']=capabilities
    registry['meta']['explicit_source_refresh']={'source':source,'sha256':hashlib.sha256(raw).hexdigest(),
        'retrieved_or_imported_at':timestamp,'pricing':price_meta,
        'note':'Model refresh is not price refresh or task validation; local import date is not upstream publication date.'}
    registry['meta']['collected_at']=timestamp[:10]
    registry['meta'].pop('reverified_at',None)
    registry['meta']['freshness']={'model_sha256':hashlib.sha256(raw).hexdigest(),'checked_at':timestamp,'source':source}
    registry['meta']['coverage_lists']={'duplicate_endpoints':[], 'added_vs_retained':sorted({c['id'] for c in capabilities}-set(previous))}
    return registry


def main(argv:list[str]|None=None)->int:
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--check',action='store_true')
    ap.add_argument('--refresh',action='store_true')
    ap.add_argument('--models-registry',type=Path)
    ap.add_argument('--pricing',type=Path)
    args=ap.parse_args(argv)
    if args.refresh and args.models_registry:
        ap.error('Choose --refresh or --models-registry, not both')
    if args.pricing and not (args.refresh or args.models_registry):
        ap.error('--pricing requires an explicit model input or --refresh')
    registry=load(ROOT/DOC/'data/runninghub-api-registry.json')
    if args.refresh or args.models_registry:
        if args.refresh:
            with urllib.request.urlopen(MODELS_URL,timeout=60) as response:
                raw=response.read()
            source=MODELS_URL
        else:
            raw=args.models_registry.read_bytes()
            source='explicit-local-official-snapshot:'+args.models_registry.name
        registry=refresh(registry,raw,source,args.pricing.read_bytes() if args.pricing else None)
    changed=write_outputs(ROOT,outputs(ROOT,registry),args.check)
    print(('DRIFT: ' if args.check else 'Updated: ')+', '.join(changed) if changed else 'All generated outputs match their inputs.')
    return int(args.check and bool(changed))


if __name__=='__main__':
    raise SystemExit(main())
