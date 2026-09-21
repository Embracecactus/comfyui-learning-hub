import json,hashlib,re
from pathlib import Path
import argparse
ap=argparse.ArgumentParser(description='Import the hash-verified 2026-09-21 anonymous public captures; never calls paid APIs')
ap.add_argument('--research-dir',type=Path,required=True)
ap.add_argument('--initial-dir',type=Path,required=True)
ap.add_argument('--root',type=Path,default=Path(__file__).resolve().parents[1])
a=ap.parse_args()
P=a.research_dir;B=a.root/'docs/05-RunningHub-API/data';B.mkdir(exist_ok=True,parents=True)
read=lambda n:json.loads((P/n).read_text())
index=read('index.json');cat=read('catalogues.json')[0];records=cat['page']['records'];rmap={r['id']:r for r in records}
details=read('sku-details.json');tables=read('price-tables.json')
assert len(details)==len(records)==int(cat['page']['total'])==244 and cat['page']['hasNext'] is False
assert {x['request']['id'] for x in details}==set(rmap)
models=[]
for row in details:
 assert row['status']==200 and row['body']['code']==0
 d=row['body']['data'];params=json.loads(d.get('inputConfigJson') or '[]');old=rmap[d['id']]
 # Keep parameter contracts, not unrelated frontend routing/config or marketing prose.
 fields=('fieldKey','type','required','defaultValue','options','min','max','minLength','maxLength','minValue','maxValue','multiple','paramDesc','priceRelated')
 params=[{k:p[k] for k in fields if k in p} for p in params]
 catname=old.get('categoryName') or ''
 is_video=('video' in catname and not catname.startswith('video-to-audio')) or catname in ('motion-control','digital-human') or d['rhEndpoint']=='/arklin/video-super-resolution'
 def opts(keys):
  for p in params:
   if p.get('fieldKey') in keys:return [str(o.get('value') if isinstance(o,dict) else o) for o in p.get('options') or []]
  return []
 models.append({'sku_id':d['id'],'id':d['rhEndpoint'].lstrip('/'),'name_cn':d['name'],'name_en':d.get('nameEn'),'category':catname,'output_type':'video' if is_video else 'other','params':params,'resolution_options':opts(('resolution','targetResolution')),'duration_options':opts(('duration',)),'observed_at':row['observed_at'],'upstream_updated_at':d.get('updateTime'),'source_url':'https://www.runninghub.cn/call-api/api-detail/'+d['id'],'detail_request':row['request'],'detail_api':row['url'],'detail_sha256':hashlib.sha256(json.dumps(d,ensure_ascii=False,sort_keys=True).encode()).hexdigest()})
models.sort(key=lambda m:m['id'])
assert len({m['id'] for m in models})==244
snapshot={'schema_version':1,'observed_at':index['collected_at'],'site':'https://www.runninghub.cn','currency_scope':'CNY (anonymous public pricing, not enterprise-account discount or billing)','authenticated':False,'paid_task_count':0,
 'provenance':{'workflow_run':'https://github.com/Embracecactus/comfyui-learning-hub/actions/runs/35573305171','artifact_id':10626612821,'artifact_sha256':'871bad89391d77006f553464096f1574524655800743d0812216a19f1bfa0bd6','collector_commit':'1e732a0eaf9eeb2c7e02041e7e45bfc183b3db81','raw_files_sha256':{n:hashlib.sha256((P/n).read_bytes()).hexdigest() for n in ('catalogues.json','sku-details.json','price-tables.json','h3-quotes.json')},'collector_warning':'After decoding the valid complete SSR page, an additional null SSR cache entry caused a rendering-only error. The saved page total=244, hasNext=false, 244 unique records and all 244 successful detail responses were independently reconciled; no rows were inferred.'},
 'catalogue':{'source_url':cat['url'],'request_cache_key':cat['cache_key'],'pagination':{k:v for k,v in cat['page'].items() if k!='records'},'record_count':len(models),'scope':'Anonymous CN STANDARD_MODEL view; not all regions, LLM channels, private/dynamic applications or all historical endpoints. Missing from this view does not mean discontinued.'},
 'models':models,'price_tables':tables,'h3_public_calculations':read('h3-quotes.json'),
 'upstream_files_check':json.loads((a.initial_dir/'index.json').read_text())['sources'][:3],
 'access_checks':[{'source_url':'https://www.runninghub.cn/third-party-fees','result':'login_required_for_full_node_fee_page','observed_at':index['collected_at'],'page_text':'登录后查看 API 价格；登录后可查看完整的模型与工作流节点计费说明'}, {'source_url':'https://www.runninghub.cn/vip-rights/2?defaultPlan=year_top','result':'redirected_to_sso_login','observed_at':index['collected_at']}, {'source_url':'https://www.runninghub.cn/call-api/bill-task?tab=keys&type=exclusive','result':'redirected_to_sso_login','observed_at':'2026-09-21T07:21:04Z'}, {'source_url':'https://www.runninghub.cn/enterprise-api/sharedApi','result':'redirected_to_sso_login','observed_at':'2026-09-21T07:21:04Z'}],
 'authorized_runtime':{'environment_rh_credentials_present':False,'conventional_repo_secret_inputs':{'RH_API_KEY_configured':False,'RH_ENTERPRISE_API_KEY_configured':False},'private_task_queries':0,'paid_tasks':0,'note':'Only these two conventional secret inputs were checked as booleans. This does not enumerate all repository secrets or inspect the user PC.'}}
# Public model examples can contain expiring cloud credentials. Never publish them.
redactions = 0
url_pattern = re.compile(r"https?://[^\s\"'<>]+", re.I)
secret_pattern = re.compile(r"\b(?:AKID|AKIA|ASIA)[A-Za-z0-9]{12,}\b")
def sanitize(value):
 global redactions
 if isinstance(value, dict):return {k:sanitize(v) for k,v in value.items()}
 if isinstance(value, list):return [sanitize(v) for v in value]
 if not isinstance(value, str):return value
 def url_replace(match):
  u=match.group(0)
  return '[REDACTED_SIGNED_URL]' if re.search(r'(q-ak|q-signature|x-amz-|x-cos-|signature=|access_token=|apikey=|api_key=)',u,re.I) else u
 clean=url_pattern.sub(url_replace,value)
 clean=secret_pattern.sub('[REDACTED_CREDENTIAL]',clean)
 if clean!=value:redactions+=1
 return clean
snapshot=sanitize(snapshot)
snapshot['sanitization']={'policy':'Remove signed example media URLs and credential-shaped identifiers; source hashes refer to original research responses. No push-protection bypass.','changed_string_fields':redactions}
f=B/'public-pricing-20260921.json';f.write_text(json.dumps(snapshot,ensure_ascii=False,indent=1)+'\n',encoding='utf-8')
print('snapshot bytes',f.stat().st_size,'video',sum(m['output_type']=='video' for m in models),'2k',sum(m['output_type']=='video' and '2k' in [r.lower() for r in m['resolution_options']] for m in models))
