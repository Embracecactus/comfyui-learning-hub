#!/usr/bin/env python3
"""Deterministic RunningHub handoff build (stdlib only, offline by default).

Model contracts/historical kit prices live in runninghub-api-registry.json.
Dated price overrides, run summaries and plans live in handoff-evidence.json.
Never import a price from prose, extrapolate endpoint families, or treat null as 0.
"""
from __future__ import annotations

import argparse
import copy
import csv
import hashlib
import html
import io
import json
import os
import tempfile
from collections import Counter
from decimal import Decimal
from pathlib import Path
import rh_survey_public as public

ROOT = Path(__file__).resolve().parents[1]
DOC = Path('docs/05-RunningHub-API')
H3 = 'minimax/hailuo-h3/text-to-video'
REGEN = 'minimax/hailuo-h3/regeneration-text-to-video'
UPSCALER = 'rhart-video/video-upscaler'
LABELS = {
    'direct_text': '仅提示词直出',
    'optional_media': '无媒体输入待验证',
    'required_media': '需前置媒体生成及计费',
    'regeneration': '需768P源视频及最终提示词',
    'upscaler': '需源视频的增强/超分（非H3再生成接口）',
    'template': '模板输入；非通用单提示词',
    'excluded_no_2k': '无2K标签（不纳入2K比较）',
    'unclassified': '输入契约待确认',
}


def text_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, indent=1) + '\n'


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding='utf-8-sig'))


def resolutions(model: dict) -> list[str]:
    return [str(v) for v in model.get('resolution_options', [])]


def load_evidence(root: Path = ROOT) -> dict:
    return public.apply(load(root / DOC / 'data/handoff-evidence.json'), root, DOC)


def m_processing(model: dict) -> bool:
    return model.get('category') == 'video-tools' and any(
        p.get('type') == 'VIDEO' for p in model.get('params', []))


def classification(model: dict) -> str:
    ep = model['id']
    if not any(v.lower() == '2k' for v in resolutions(model)):
        return 'excluded_no_2k'
    if '/regeneration-' in ep:
        return 'regeneration'
    if ep == UPSCALER or ep.endswith('/video-super-resolution') or m_processing(model):
        return 'upscaler'
    params = model.get('params', [])
    if 'prompt' not in {p['fieldKey'] for p in params}:
        return 'template' if any(p['fieldKey'] == 'templateId' for p in params) else 'unclassified'
    if ep.endswith('/text-to-video'):
        return 'direct_text'
    if any(p.get('required') and p.get('type') in ('IMAGE', 'VIDEO', 'AUDIO') for p in params):
        return 'required_media'
    # Optional media in the schema does not prove a text-only request works.
    return 'optional_media'


def rate(model: dict, resolution: str, evidence: dict) -> dict:
    """Return only an exact endpoint+resolution price; never borrow sibling prices."""
    for p in evidence['platform_prices']:
        if p['endpoint'] == model['id'] and p['resolution'].lower() == resolution.lower():
            return {'cny': p['rate_cny'], 'unit': p['unit'], 'level': p['verification'],
                    'source': p['source_id'], 'date': p['observed_at'], 'exact': p.get('unconditional', True),
                    'constraints': p.get('constraints', {})}
    p = model.get('pricing', {})
    if p.get('status') != 'official_listed_price' or p.get('currency') != 'CNY':
        return {'cny': None, 'unit': None, 'level': 'price_gap', 'source': '', 'date': '', 'exact': False}
    field = 'targetResolution' if model['id'] == UPSCALER else 'resolution'
    rules = [r for r in p.get('rules') or []
             if str(r.get('when', {}).get(field, '')).lower() == resolution.lower()]
    # Other parameters may change the price. Do not silently select one of them.
    chosen = rules[0] if len(rules) == 1 and set(rules[0].get('when', {})) == {field} else None
    val = chosen.get('price') if chosen else None
    if not p.get('rules') and not p.get('depends_on'):
        val = p.get('price')
    exact = p.get('unit') in ('/秒', '/second', 'CNY/billable_output_second')
    return {'cny': str(val) if val is not None else None, 'unit': p.get('unit'),
            'level': 'historical_official_snapshot' if val is not None else 'conditional_price_gap',
            'source': 'developer-kit-pricing-20260429', 'date': p.get('snapshot_version', ''),
            'exact': exact}


def money(value: str | Decimal | None, seconds: int = 1) -> str:
    return '' if value is None else f'{Decimal(str(value)) * seconds:.2f}'


def source_note(evidence: dict, source_id: str) -> str:
    source = next((s for s in evidence['sources'] if s['id'] == source_id), {})
    return source.get('url', '')


def normalize(registry: dict, evidence: dict) -> dict:
    r = copy.deepcopy(registry)
    eps = [m['id'] for m in r['model_capabilities']]
    if len(eps) != len(set(eps)):
        raise ValueError('Duplicate model endpoint; refusing to publish misleading coverage')
    for m in r['model_capabilities']:
        m['supports_2k'] = any(x.lower() == '2k' for x in resolutions(m))
        m['supports_768p'] = any(x.lower() == '768p' for x in resolutions(m))
        m['single_prompt_2k'] = classification(m) if m.get('output_type') == 'video' else 'not_video'
        m['platform_price_evidence'] = [p for p in evidence['platform_prices'] if p['endpoint'] == m['id']]
        if m['id'] == H3:
            m['verification_status'] = 'schema_verified+reported_runs_via_personal_app_or_open_workflow'
            m['verification_notes'] = [
                '三次个人应用2K与一次云端开源768P历史记录见run_evidence；本轮未重新调用私人任务。',
                '标准模型API与regeneration没有企业实跑证据；不外推图生/多模态或其他模型。',
                '414为历史拒绝；同应用09-16/17已报告成功，根因未确认。']
    fam = r['endpoint_families']
    if not any(f['id'] == 'account-status' for f in fam):
        fam.append({'id':'account-status', 'family':'账户状态', 'method':'POST',
                    'path':'/uc/openapi/accountStatus',
                    'auth':{'type':'bearer+body', 'body_key':'apikey'},
                    'key_types_allowed':['consumer-member','enterprise-shared','enterprise-dedicated'],
                    'instances':1, 'verification':'documented+offline_contract_tested',
                    'sources':[source_note(evidence,'personal-runs-20260917')],
                    'notes':'仅账户状态，不是完整账单接口。本轮不查询私人余额。'})
    for f in fam:
        if f['id'] == 'workflow-webhook':
            f['notes'] = '事件详情/重发接口已出现在09-21官方文档导航；旧版未发现的结论不再适用。当前清单不声称HTTP全量。'
    r['run_evidence'] = copy.deepcopy(evidence['reported_runs'])
    r['channel_history'] = copy.deepcopy(evidence['channel_history'])
    r['gaps'] = copy.deepcopy(evidence['gaps'])
    r['pricing_anchors'] = {'platform_exact_endpoint_records':copy.deepcopy(evidence['platform_prices']),
                            'note':'原厂参考价不作为RunningHub报价；旧引用保留在Git历史。'}
    meta = r['meta']
    meta['schema_version'] = 2
    meta['handoff_maintained_at'] = evidence['maintained_at']
    meta['coverage_statement'] = '模型覆盖以保留快照为界；HTTP接口族为已整理清单，不声称当前全平台全量。'
    meta['key_types'] = {p['key_type']:p['apis'] for p in evidence['plans']}
    meta['account_owner_vs_key_type'] = '个人/团队为结算主体，消费级/企业共享/独占为Key类型，不混同。'
    meta['counts']['http_endpoint_families'] = len(fam)
    meta['counts']['http_endpoint_instances_curated'] = sum(f.get('instances',0) for f in fam if isinstance(f.get('instances'),int))
    video = [m for m in r['model_capabilities'] if m.get('output_type') == 'video']
    meta['counts'].update(model_capabilities=len(eps), video_capabilities=len(video),
                          video_supports_2k=sum(m['supports_2k'] for m in video),
                          video_supports_768p=sum(m['supports_768p'] for m in video),
                          single_prompt_2k_direct=sum(classification(m)=='direct_text' for m in video),
                          reported_personal_2k_runs=sum(t['route']=='personal-ai-app' for t in evidence['reported_runs']))
    priced = {m['id'] for m in r['model_capabilities'] if m['pricing'].get('status')=='official_listed_price'}
    reported = {p['endpoint'] for p in evidence['platform_prices']}
    missing = sorted(set(eps) - priced - reported)
    meta['counts']['model_capabilities_with_public_price'] = len(priced)
    meta['counts']['additional_endpoints_with_reported_page_price'] = len(reported-priced)
    meta['counts']['model_capabilities_missing_public_price'] = len(missing)
    meta['counts']['verified_live_this_workspace'] = ['Current anonymous official price tables and six H3 web calculations verified; no new private task queries or paid tasks.'] if evidence.get('_public_snapshot') else ['Historical records only; no paid task verification.']
    if evidence.get('_public_snapshot'):
        meta['public_cn_catalogue'] = copy.deepcopy(evidence['_public_snapshot']['catalogue'])
        meta['public_price_observed_at'] = evidence['_public_snapshot']['observed_at']
    meta.setdefault('coverage_lists', {})['missing_public_price'] = missing
    meta['coverage_lists']['note'] = '历史定价快照与有日期的页面报告分列；目录不等于实跑或当前价格验证。'
    meta['lifecycle_conventions']['error_codes'] = '1014权限拒绝；421并发拒绝；414历史未明原因拒绝，不推断余额或自动重试。'
    meta['lifecycle_conventions']['concurrency'] = '权益见handoff-evidence.json；任务提交结果不确定时严禁盲重试。'
    return r


def cost_rows(registry: dict, evidence: dict, res: str) -> list[dict]:
    rows = []
    for m in evidence.get('_live_models', registry['model_capabilities']):
        if m.get('output_type') != 'video' or res.lower() not in [x.lower() for x in resolutions(m)]:
            continue
        kind = classification(m) if res.lower() == '2k' else ('direct_text' if m['id'].endswith('/text-to-video') else 'optional_media')
        p = rate(m, res, evidence)
        complete = kind == 'direct_text' and p['cny'] is not None and p['exact'] and p['unit'] in ('/秒', '/second', 'CNY/billable_output_second')
        row = {'route_id':f"standard:{m['id']}:{res}", 'endpoint':m['id'], 'resolution':res,
               'key_type':'enterprise-shared', 'route_class':kind, 'single_prompt':kind=='direct_text',
               'price_per_second_cny':p['cny'] or '', 'price_unit':p['unit'] or '',
               'price_evidence':p['level'], 'price_date':p['date'], 'source_id':p['source'],
               'source_url':next((x.get('source_url') for x in evidence['platform_prices'] if x['endpoint']==m['id'] and x['resolution'].lower()==res.lower()), None) or source_note(evidence,p['source']),
               'duration_options':'|'.join(m.get('duration_options', [])),
               'actual_pixels':'未验证（标签不能代替媒体检查）',
               'five_second_cost':'', 'ten_second_cost':'', 'fifteen_second_cost':'',
               'full_cost_status':'dated_quote_not_live_bill' if complete else 'incomplete',
               'unknowns':'提交前复核价格；失败/取消费及固定费用不在成功单任务报价内。' if complete else '前置输入、再生成/超分源视频或附加收费未闭合；模型阶段价格不等于从头总价。'}
        for seconds, col in [(5,'five_second_cost'),(10,'ten_second_cost'),(15,'fifteen_second_cost')]:
            supported = str(seconds) in m.get('duration_options', [])
            row[col] = '¥'+money(p['cny'],seconds) if complete and supported else ('不支持该时长' if complete else '未核验')
        rows.append(row)
    personal = {'route_id':f'personal-h3-{res}', 'endpoint':H3, 'resolution':res,
                'key_type':'consumer-member', 'route_class':'personal-ai-app', 'single_prompt':True,
                'price_per_second_cny':'', 'price_unit':'CNY + RH_coin', 'price_evidence':'reported_live_run_not_requeried' if res=='2K' else 'not_measured',
                'price_date':'2026-09-17' if res=='2K' else '', 'source_id':'personal-runs-20260917',
                'source_url':source_note(evidence,'personal-runs-20260917'), 'duration_options':'|'.join(str(i) for i in range(5,16)),
                'actual_pixels':'历史实测2560×1440@24fps' if res=='2K' else '未测',
                'five_second_cost':'未核验',
                'ten_second_cost':'未核验',
                'fifteen_second_cost':'未核验',
                'full_cost_status':'mixed_units_no_cny_total', 'unknowns':'币兑人民币、会员费分摊、10/15秒附加币未知；个人应用价不等于企业价。'}
    # Values for measured route come from evidence, never a second literal tariff.
    samples = sorted([r for r in evidence['reported_runs'] if r['route']=='personal-ai-app'
                      and r['request']['resolution']==res and str(r['usage']['output_seconds'])=='5'], key=lambda r:r['date'])
    if res=='2K' and samples:
        last = samples[-1]
        personal['price_date'] = last['date']
        amounts = {str(s['usage']['thirdPartyConsumeMoney']) for s in samples}
        coins = [Decimal(str(s['usage']['consumeCoins'])) for s in samples]
        personal['five_second_cost'] = '历史实测 ¥' + '/'.join(sorted(amounts)) + f' + {min(coins)}–{max(coins)} RH币'
        for sec,col in [(10,'ten_second_cost'),(15,'fifteen_second_cost')]:
            personal[col] = '按5秒样本线性模型费预算 ¥'+money(Decimal(str(last['usage']['thirdPartyConsumeMoney']))/Decimal(str(last['usage']['output_seconds'])),sec)+' + RH币未知（未实测）'
    rows.append(personal)
    if res=='768P':
        cloud = next(r for r in evidence['reported_runs'] if r['route']=='personal-open-workflow')
        rows.append({**personal, 'route_id':'personal-open-h3-768p', 'endpoint':'workflow:h3-t2v-open-768p-cloud.json',
                     'route_class':'personal-open-workflow', 'actual_pixels':'历史实测1344×768@24fps',
                     'five_second_cost':f"历史实测{cloud['usage']['consumeCoins']} RH币／{cloud['media']['duration_seconds']}媒体秒；{cloud['usage']['taskCostTime']}运行秒",
                     'ten_second_cost':'未知（不按运行时间线性外推）', 'fifteen_second_cost':'未知（不按运行时间线性外推）',
                     'price_evidence':'reported_live_run_not_requeried', 'price_date':cloud['date'],
                     'source_id':'registry-snapshot-20260913','source_url':source_note(evidence,'registry-snapshot-20260913'),
                     'unknowns':'云端运行秒计费；冷启动/长度非线性；不是标准模型API768P档证据。'})
    else:
        for ep,kind in [(REGEN,'two-stage-regeneration'),(UPSCALER,'two-stage-upscaler')]:
            rows.append({**personal, 'route_id':kind, 'endpoint':H3+' -> '+ep,
                         'key_type':'enterprise-shared', 'route_class':kind, 'resolution':'768P->2K',
                         'actual_pixels':'双阶段未实测', 'five_second_cost':'未核验',
                         'ten_second_cost':'未核验', 'fifteen_second_cost':'未核验',
                         'price_unit':'CNY / distinct stage billing units', 'price_evidence':'incomplete_stage_chain',
                         'price_date':'', 'source_id':'h3-regen-contract-20260921' if ep==REGEN else 'developer-kit-pricing-20260429',
                         'source_url':source_note(evidence,'h3-regen-contract-20260921' if ep==REGEN else 'developer-kit-pricing-20260429'),
                         'full_cost_status':'incomplete',
                         'unknowns':'总价=768P账单+阶段2账单+明确独立收费项；按任务/字段范围去重，不能直接累加父子总额。' if ep==REGEN else '总价=p768×生成计费秒+p_upscale×超分输入计费秒；5.167媒体秒未必按5秒计费；非原生/生成式2K等价。'})
    if res == '2K' and evidence.get('_public_snapshot'):
        live = {m['id']: m for m in evidence['_live_models']}
        a = rate(live[H3], '768P', evidence)
        b = rate(live[REGEN], '2K', evidence)
        u = rate(live[UPSCALER], '2K', evidence)
        for row in rows:
            if row['route_class'] not in ('two-stage-regeneration','two-stage-upscaler'):
                continue
            row['source_id'] = public.SOURCE_ID
            row['source_url'] = source_note(evidence, public.SOURCE_ID)
            row['price_date'] = evidence['_public_snapshot']['observed_at'][:10]
            row['price_evidence'] = 'official_stage_prices_not_live_chain'
            row['full_cost_status'] = 'public_stage_formula_not_live_bill'
            row['unknowns'] = ('再生成仅按输出计费的公开价表；两阶段实际计费秒与舍入未实测。'
                               if row['route_class']=='two-stage-regeneration' else
                               '超分按max(ceil(媒体秒),5)；真实源片时长不能直接等同请求秒。')
            for seconds, col in [(5,'five_second_cost'),(10,'ten_second_cost'),(15,'fifteen_second_cost')]:
                if row['route_class']=='two-stage-regeneration' and a['cny'] and b['cny'] and b['exact']:
                    total = public.regeneration_budget(seconds, seconds, a['cny'], b['cny'])
                    row[col] = f'两阶段各计费{seconds}秒时预算 ¥{total:.2f}（未实扣）'
                elif row['route_class']=='two-stage-upscaler' and a['cny'] and u['cny']:
                    total = public.upscale_budget(seconds, str(seconds), a['cny'], u['cny'])
                    row[col] = f'源生成计费及源媒体均恰为{seconds}秒时预算 ¥{total:.2f}（未实扣）'
    return rows


def csv_text(rows: list[dict]) -> str:
    out = io.StringIO(newline='')
    fields = list(dict.fromkeys(k for row in rows for k in row))
    w = csv.DictWriter(out, fields, lineterminator='\n')
    w.writeheader()
    w.writerows(rows)
    return '\ufeff'+out.getvalue()


def table(headers: list[str], rows: list[list[object]]) -> str:
    def escape(v): return str(v if v is not None else '未知').replace('|','\\|').replace('\n',' ')
    return '\n'.join(['| '+' | '.join(headers)+' |','|'+'|'.join(['---']*len(headers))+'|']+
                     ['| '+' | '.join(escape(v) for v in r)+' |' for r in rows])


def outputs(root: Path = ROOT, registry: dict | None = None) -> dict[Path, str]:
    base = root / DOC
    evidence = load_evidence(root)
    registry = normalize(registry or load(base/'data/runninghub-api-registry.json'), evidence)
    models = registry['model_capabilities']
    counts = registry['meta']['counts']
    public_result, public_summary = public.publication(evidence['_public_snapshot'], registry, csv_text, table, classification) if evidence.get('_public_snapshot') else ({}, '')
    rows2,rows7 = cost_rows(registry,evidence,'2K'), cost_rows(registry,evidence,'768P')
    routes = [{'endpoint':m['id'],'supports_2k':m['supports_2k'], 'decision':m['single_prompt_2k'],
               'reason':LABELS.get(m['single_prompt_2k'],'待核'),
               'required_inputs':'|'.join(p['fieldKey'] for p in m['params'] if p.get('required')),
               'resolutions':'|'.join(resolutions(m)), 'duration_options':'|'.join(m.get('duration_options',[])),
               'verification':'schema_snapshot_only; run evidence separately scoped'}
              for m in models if m.get('output_type')=='video']
    cat = [{'endpoint':m['id'], 'name':m.get('name_cn'), 'output_type':m.get('output_type'),
            'resolutions':'|'.join(resolutions(m)), 'duration_options':'|'.join(m.get('duration_options',[])),
            'supports_768p':m['supports_768p'], 'supports_2k':m['supports_2k'],
            'single_prompt_2k':m['single_prompt_2k'],
            'historical_price':json.dumps(m['pricing'],ensure_ascii=False,separators=(',',':')),
            'dated_page_evidence':json.dumps(m['platform_price_evidence'],ensure_ascii=False,separators=(',',':')),
            'verification':m['verification_status']} for m in models]
    planrows=[]
    for plan in evidence['plans']:
        for api in ['model','llm','ai-app','workflow']:
            planrows.append({'key_type':plan['key_type'],'api_type':api,'allowed':api in plan['apis'],
                'concurrency':json.dumps(plan.get('concurrency',plan.get('default_concurrency')),ensure_ascii=False),
                'rates':json.dumps(plan.get('instance_rates',{}),ensure_ascii=False),
                'rate_unit':plan.get('rate_unit','rental + model node fee'),
                'rental_or_membership_cny':'unknown', 'source_id':plan['source_id'], 'verification':plan['verification']})
    personal = [r for r in evidence['reported_runs'] if r['route']=='personal-ai-app']
    p = rate(next(m for m in models if m['id']==H3),'2K',evidence)
    p768 = rate(next(m for m in models if m['id']==H3),'768P',evidence)
    intro = f'> 自动生成于证据维护版本 {evidence["maintained_at"]}；模型集合日期 {registry["meta"]["collected_at"]}。这不是实时全平台或全账户验收。\n> 输入：`data/handoff-evidence.json`（价格/证据/权益）与 `data/runninghub-api-registry.json`（模型契约与历史价格快照）。不要手改生成文件。\n'
    price_table = table(['渠道','5秒','10秒','15秒','状态'],[
        ['企业共享H3文生2K',*(f'¥{money(p["cny"],s)}' for s in [5,10,15]),p['date']+'官方公开价；非企业实扣账单'],
        ['企业共享H3文生768P',*(f'¥{money(p768["cny"],s)}' for s in [5,10,15]),'精确文生端点，不外推其他H3家族'],
        ['个人AI应用2K',*(next(r for r in rows2 if r['route_id']=='personal-h3-2K')[k] for k in ['five_second_cost','ten_second_cost','fifteen_second_cost']),'混合单位，人民币总成本未闭合'],
        ['768P→regeneration 2K',*(next(r for r in rows2 if r['route_id']=='two-stage-regeneration')[k] for k in ['five_second_cost','ten_second_cost','fifteen_second_cost']),'公开阶段预算，不是实际账单'],
        ['独占GPU应用/工作流','租金未知','利用率未知','摊销未知','租期内运行秒增量为0不代表总成本为0']])
    run_table = table(['日期','taskId','第三方费(元)','RH币','计费输出秒','媒体秒','运行秒'],[
        [r['date'],r['task_id'],r['usage']['thirdPartyConsumeMoney'],r['usage']['consumeCoins'],r['usage']['output_seconds'],r['media']['duration_seconds'],r['usage']['taskCostTime']] for r in personal])
    gap_table=table(['缺口','证据状态','说明','关闭所需证据'],[[g['id'],g['status'],g['detail'],g['closure_evidence']] for g in evidence['gaps']])
    references='\n'.join(f'- [{s["id"]}]({s["url"]})：{s["observed_at"]}；{s["evidence_level"]}。' for s in evidence['sources'])
    coverage=table(['维度','数量'],[[k,counts[k]] for k in ['model_capabilities','video_capabilities','video_supports_768p','video_supports_2k','single_prompt_2k_direct','model_capabilities_with_public_price','additional_endpoints_with_reported_page_price','model_capabilities_missing_public_price','http_endpoint_families']])
    routing=table(['分类','数量'],[[LABELS[k],v] for k,v in sorted(Counter(r['decision'] for r in routes).items())])
    costs_md = '# RunningHub 768P / 2K 成本与证据报告\n\n'+intro+'\n'+public_summary+'\n\n## 可用于预算的价格与边界\n\n'+price_table+'''

上表模型费用的“秒”是计费输出秒，不是 GPU 运行秒，也不是容器测得媒体时长。个人样本请求/计费5秒而媒体5.167秒，分别保存。个人10/15秒仅对第三方费作预算演算，附加币、失败/退款和固定费用未知；不是保证成交价。

2K 直出不额外虚构一次768P任务扣费。两阶段路线必须累加两个独立阶段的实际账单；父/子任务与query/outputs重复出现的同一费用不得重复累计。

## 个人版历史样本（本轮未重新查询私人任务）

'''+run_table+'''

原始页面与不可变Git版本见来源。导入这些记录不等于本轮重新跑通。云端开源H3 768P样本用量见cost-768p.csv，10/15秒成本未知，不按运行时间线性外推，也不等于标准模型API档位的证据。

414保留为09-14/15历史拒绝；同一应用09-16/17已有后续成功报告。余额耗尽、每日额度、平台内部原因均未获得可证明的根因，不能再次要求用户按猜测充值。

## 两阶段完整成本

- 再生成：`C_total = C_768P_source_task + C_regeneration_task + verified_independent_charges`。RunningHub文生regeneration公开输出单价已核实；预算见表，实际账单/计费秒仍未核验。不能把多模态原始参考素材的重计费套到文生链路的生成源视频。
- 普通超分：`C_total = p768 × generation_billable_seconds + p_upscale × input_billable_seconds + independent_charges`。RH超分2K按max(ceil(输入媒体秒),5)计费；媒体5.167秒对应6个计费秒，不能按5秒计算；不同增强算法均不等同H3 regeneration。
- `baseVideoUrl`与最终提示词必须属于同一源任务。仅凭相同分辨率不能证明开源工作流视频可被标准regeneration接受。
- 使用`examples/python/rh_evidence_audit.py`完成只读报价/旧任务采集、源视频检查与两个阶段账单对账。它不创建付费任务；缺密钥返回明确阻塞，缺字段不视为0。

## 个人 / 企业成本口径

消费级使用AI应用/工作流；企业共享支持标准模型、LLM、应用和工作流；独占只支持应用/工作流。个人/团队账户主体与Key类型是两个维度。

企业共享直接模型API按模型价格；工作流/应用还应计实例及可计费保留时间：`C = model_node_fees + hourly_rate × (runtime_seconds + independently_billable_retention_seconds) / 3600`。若运行时间已经含保留时间，不得再加一次。

独占比较必须加机器租金分摊：`(rental + all_model_fees + failed_task_fees + other_verified_charges) / accepted_output_count`。个人会员费、充值币与赠送币的实际成本也要按明确周期分摊，禁止猜测币兑人民币。

并发影响容量，不自动降低每任务价格。完整三类Key×四类API矩阵见`data/personal-enterprise-matrix.csv`，权益数字是09-17页面报告，不是本轮企业账单或超额扩容报价。

## 验收缺口

'''+gap_table+'\n\n## 来源\n\n'+references+'\n'
    survey_md='# RunningHub API 目录与单提示词2K纳入规则\n\n'+intro+'\n'+public_summary+'\n\n## 保留GitHub快照覆盖清单\n\n'+coverage+'\n\n'+routing+'''

`data/prompt-2k-routes.csv`逐行覆盖保留快照中的所有视频条目，含纳入/排除原因；无2K、模板、需媒体、处理器不得混成“单提示词已可用”。仅文生端点算直接候选，仍需区分契约存在、价格记录和实跑成功。可选媒体参数不保证无媒体调用一定成功。

`data/live-model-capabilities.csv`为当天匿名中国站完整列表；`data/live-2k-price-tables.csv`为全部显式2K视频价表，保留附加费、帧率/模式和最低计费规则。`data/cost-2k.csv`按该当前视图生成，包含显式2K端点、个人应用及两种两阶段路线。图生/多模态/处理器的模型单价与前置费用分别表示，总价未知就留为未核验。`data/cost-768p.csv`覆盖所有768P标签端点与个人应用/云工作流；当前平台价格按逐SKU价表绑定，不把文生价格套到Max/Turbo/图生/多模态。

模型注册表仍保留353条历史官方定价，不再用一篇新HTML替代机器数据。HTTP接口族是已整理清单，并非当前全量：账户状态接口已补；官方文档导航已列出webhook事件详情/重发，旧“未发现”的结论已撤回，但未将未读取完整契约的接口冒称已验证。

## 接入与安全

客户端提供账户预检、免费price-preview、提交闸门、两类响应格式、任务恢复、媒体检查与脱敏。标准模型返回顶层taskId；旧应用/工作流通常为code=0、data.taskId。收到taskId立刻保存。超时后只resume；提交网络状态不确定保留SUBMISSION_UNCERTAIN，不自动重提。

匿名网页公开报价已经采集；企业账户专属price-preview、折扣和实扣仍需相应Key。没有有效预估时标准模型客户端默认阻止付费创建；必须显式`--allow-unpriced`才允许用户承担未知费用。无密钥dry-run不联网；历史样本只读重查需环境变量，自动化测试不加载账户凭据。

仅复用本仓库API客户端与JSON，不新增面向公网的托管代理，不开放用户余额给第三方。实际秘钥、签名URL、私有余额和媒体留在gitignored的output目录，分享使用脱敏摘录。

## 来源与范围

'''+references+'\n'
    readme = '# RunningHub API 接入与成本资料\n\n'+intro+'''

## 入口

[API与覆盖报告](01-调研报告.md) · [完整成本报告](02-768P-2K费用报告.md) · [HTML报告](runninghub-h3-2k-api.html) · [实际接入与验收](04-接入与费用验收.md) · [当天公开价目与目录复核](06-公开报价与目录复核.md)

## 当前结论

'''+public_summary+'\n\n'+price_table+'''

本版本完成资料/数据/客户端一致性修复，不把“离线验收通过”当作“所有企业和两阶段账单已实跑通过”。具体缺口及关闭标准在费用报告中逐项列出。

## 生成与检查

```bash
python3 scripts/rh_survey_build_registry.py           # 离线重建；不谎报新采集日期
python3 scripts/rh_survey_build_cost_tables.py        # 同一生成器，非第二套手写价格
python3 scripts/rh_survey_build_cost_tables.py --check # 只校验，发现漂移时退出非0
python3 -m unittest discover -s tests/scripts -p 'test_rh_handoff*.py' -v
```

显式刷新模型快照使用`python3 scripts/rh_survey_build_registry.py --refresh`，或`--models-registry <官方JSON>`；可用`--pricing <官方pricing.public.json>`更新对应历史价格来源。下载失败不覆盖已提交数据；价格覆盖只匹配精确端点+分辨率。刷新目录不自动刷新价目或任务证据。

## 最小调用

```bash
CLIENT=docs/05-RunningHub-API/examples/python/rh_min_client.py
# 无密钥、无网络的计划检查
python3 "$CLIENT" run minimax/hailuo-h3/text-to-video \\
  '{"prompt":"一只橙猫在雨后屋顶缓慢行走","resolution":"2K","duration":"5","ratio":"16:9"}'
# 通过安全环境变量配置RH_API_KEY后，以下只读命令可用
python3 "$CLIENT" account
python3 "$CLIENT" price minimax/hailuo-h3/text-to-video \\
  '{"prompt":"一只橙猫在雨后屋顶缓慢行走","resolution":"2K","duration":"5","ratio":"16:9"}'
# 只有明确增加 --execute 才可能创建付费任务；不要在仓库或shell历史里写真实Key
```

## 数据契约

`runninghub-api-registry.json`：模型契约/历史价格；`handoff-evidence.json`：有日期的历史样本、权益和缺口，并以SHA256绑定`public-pricing-20260921.json`的当日官方网页原始报价和目录；所有CSV/报告/HTML由这些明确来源生成。新增价格必须写来源、日期、单位、精确端点与证据等级。未知不是零；页面报告不是本轮实测；实际像素不同于分辨率标签。

CSV采用UTF-8 BOM和英文机器字段。`price_per_second_cny`只表示该模型阶段单价；`five_second_cost`等才表示标注条件下的总价/预算，不完整路线必须保留`full_cost_status=incomplete`。计费输出秒、媒体秒和运行秒分别建模。
'''
    result={DOC/'data/runninghub-api-registry.json':text_json(registry),
            DOC/'data/model-capabilities.csv':csv_text(cat), DOC/'data/cost-2k.csv':csv_text(rows2),
            DOC/'data/cost-768p.csv':csv_text(rows7), DOC/'data/prompt-2k-routes.csv':csv_text(routes),
            DOC/'data/personal-enterprise-matrix.csv':csv_text(planrows),
            DOC/'01-调研报告.md':survey_md, DOC/'02-768P-2K费用报告.md':costs_md, DOC/'README.md':readme}
    result.update({DOC/path:content for path,content in public_result.items()})
    snapshot=load(base/'data/sources-snapshot.json')
    if evidence.get('_public_snapshot'):
        snapshot['public_cn_evidence'] = evidence['_public_snapshot']['provenance']
        snapshot['official_repository_files_rechecked'] = evidence['_public_snapshot']['upstream_files_check']
    snapshot['handoff_maintained_at']=evidence['maintained_at']
    snapshot['handoff_evidence_sources']=evidence['sources']
    snapshot['note']='原始collected_at/reverified_at仅描述保留快照；本轮维护日期不冒充重新采集日期。'
    if registry['meta'].get('explicit_source_refresh'):
        snapshot['explicit_source_refresh']=registry['meta']['explicit_source_refresh']
    result[DOC/'data/sources-snapshot.json']=text_json(snapshot)
    result[DOC/'runninghub-h3-2k-api.html']=render_html(evidence,counts,rows2,run_table,gap_table)
    return result


def render_html(e:dict, counts:dict, rows:list[dict], _runs:str, _gaps:str) -> str:
    def ht(head, data):
        return '<div class="scroll"><table><thead><tr>'+''.join('<th>'+html.escape(str(x))+'</th>' for x in head)+'</tr></thead><tbody>'+''.join('<tr>'+''.join('<td>'+html.escape(str(x))+'</td>' for x in row)+'</tr>' for row in data)+'</tbody></table></div>'
    priced=[r for r in rows if r['route_class']=='direct_text']
    t=ht(['单提示词2K候选','5秒预算','10秒预算','15秒预算','来源日期'],[[r['endpoint'],r['five_second_cost'],r['ten_second_cost'],r['fifteen_second_cost'],r['price_date']] for r in priced])
    runrows=ht(['日期','taskId','模型费(元)','RH币','计费秒 / 媒体秒 / 运行秒'],[[r['date'],r['task_id'],r['usage']['thirdPartyConsumeMoney'],r['usage']['consumeCoins'],f"{r['usage']['output_seconds']} / {r['media']['duration_seconds']} / {r['usage']['taskCostTime']}"] for r in e['reported_runs'] if r['route']=='personal-ai-app'])
    gaps=ht(['未闭合项','需要的证据'],[[g['detail'],g['closure_evidence']] for g in e['gaps'] if g['status'] != 'closed_public_evidence'])
    plans=ht(['Key类型','可调用API','运行费 / 单位','固定成本或缺口'],[[p['key_type'],', '.join(p['apis']),json.dumps(p.get('instance_rates',{}),ensure_ascii=False)+' '+p.get('rate_unit',''), '独占租金/会员分摊/超额并发见费用报告'] for p in e['plans']])
    return '''<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>RunningHub 2K API｜成本、证据与接入</title><style>
:root{color-scheme:dark}body{margin:0;background:#081411;color:#eef7f2;font:16px/1.75 system-ui,"Microsoft YaHei",sans-serif}main{max-width:1180px;margin:auto;padding:42px 24px 80px}h1{font-size:42px;line-height:1.2}h2{margin-top:48px;color:#9ee6bd}p,li{max-width:1000px}.note{padding:18px 22px;border:1px solid #638579;border-radius:12px;background:#10231c}a{color:#ade9c7}nav{display:flex;flex-wrap:wrap;gap:20px}.scroll{overflow:auto}table{border-collapse:collapse;width:100%;font-size:14px;margin:20px 0}td,th{padding:14px;text-align:left;border-bottom:1px solid #355446;vertical-align:top;overflow-wrap:anywhere}th{color:#b6d9c6}pre{overflow:auto;padding:18px;background:#142d21;border-radius:10px}code{font-family:Consolas,monospace}footer{margin-top:45px;color:#acc1b5}button,input{font:inherit}input{width:80px}@media print{body{color:#111;background:#fff}h2,a,th{color:#163b29}pre,.note{background:#f3f5f4;color:#111}main{padding:15px}.scroll{overflow:visible}table{font-size:10px}}
</style></head><body><main><nav><a href="#cost">价格</a><a href="#plans">个人与企业</a><a href="#evidence">证据</a><a href="#integration">接入</a><a href="#gaps">缺口</a></nav>
<h1>一个提示词，生成2K视频</h1><p>统一数据源 · 可复现构建 · 不把预算当账单</p>
<div class="note">维护日期：'''+e['maintained_at']+'''。保留的GitHub历史目录与04-29价目另列；09-21另行完整取得中国站匿名标准模型视图244个SKU及全部26个显式2K视频价表。本轮未发起付费任务、未重新查询私人任务、未验证企业实际扣费。</div>
<p>保留GitHub历史目录（非当天网站目录）：'''+str(counts['model_capabilities'])+'个模型，'+str(counts['video_supports_2k'])+'个2K标签视频端点；其中'+str(counts['single_prompt_2k_direct'])+'''个纯文生候选。当天网站目录与逐端点价表见<a href="06-公开报价与目录复核.md">公开证据复核</a>。其余图生、模板、超分、再生成独立分类，不能混成“全部单提示词可用”。</p>
<h2 id="cost">单提示词直出：日期化预算</h2>'''+t+'''
<p>仅同一任务的模型报价，不包含未知的退款、失败重试及固定费用。2K直出不额外虚构768P任务费用。个人应用另扣RH币，不能把模型费当人民币总成本。</p>
<label>H3企业文生2K预算秒数 <input id="seconds" type="number" min="5" max="15" step="1" value="5"></label> <strong id="budget"></strong>
<p>两阶段：<code>768P账单 + regeneration账单 + 独立收费项</code>。regeneration文生输出价已核实，预算按两个阶段的计费秒分别相乘；账单仍未核验，不再混用原厂¥1.10/秒。RH普通超分按输入媒体秒向上取整且至少5秒；见<a href="06-公开报价与目录复核.md">完整当日公开证据</a>。</p>
<h2 id="plans">个人 / 企业权益与总成本</h2>'''+plans+'''
<p>这是09-17公开页面的历史报告，不是企业Key实测。个人/团队账户主体与Key类型分开。企业工作流总价还含可计费实例保留时间；独占必须摊销租金，租期内运行秒增量为0不等于总成本为0。默认并发与额外扩容价分开。</p>
<h2 id="evidence">个人应用历史成功记录</h2>'''+runrows+'''
<p>媒体为2560×1440、24fps且带音轨（已有仓库记录，本轮未重新检查媒体）。414仅保留为历史拒绝；后续成功不能反推之前的故障原因。</p>
<h2 id="integration">按接口契约接入</h2><pre>CLIENT=docs/05-RunningHub-API/examples/python/rh_min_client.py
python3 "$CLIENT" account
python3 "$CLIENT" price minimax/hailuo-h3/text-to-video \\
  '{"prompt":"橙猫在雨后屋顶行走","resolution":"2K","duration":"5","ratio":"16:9"}'
# 单提示词入口，默认dry-run：
python3 "$CLIENT" video --key-type consumer-member --prompt '橙猫在雨后屋顶行走' --resolution 2K --duration 5
# video / run / run-ai-app / run-workflow 只有 --execute 才创建付费任务
# 已返回taskId后只resume，不重新创建</pre>
<p>标准模型：顶层<code>taskId</code>；旧应用/工作流：<code>code=0</code>后读取<code>data.taskId</code>。两层业务错误都要检查。预估失败不自动放行付费；提交网络中断保留<code>SUBMISSION_UNCERTAIN</code>。</p>
<p><a href="04-接入与费用验收.md">完整可执行验收步骤</a> · <a href="data/prompt-2k-routes.csv">逐端点纳入/排除清单</a> · <a href="data/handoff-evidence.json">统一证据数据</a></p>
<h2 id="gaps">未关闭的费用证据</h2>'''+gaps+'''
<h2>来源</h2><ul>'''+''.join('<li><a href="'+html.escape(s['url'],quote=True)+'">'+html.escape(s['id'])+'</a> · '+s['observed_at']+' · '+html.escape(s['evidence_level'])+'</li>' for s in e['sources'])+'''</ul>
<footer>由scripts/rh_survey_handoff.py生成；修改JSON后重建，禁止单独手改HTML价格。</footer>
<script id="price-data" type="application/json">'''+json.dumps(e['platform_prices'],ensure_ascii=False).replace('<','\\u003c')+'''</script>
<script>const prices=JSON.parse(document.getElementById('price-data').textContent);const p=prices.find(x=>x.endpoint==='minimax/hailuo-h3/text-to-video'&&x.resolution==='2K');const input=document.getElementById('seconds');function update(){const n=Number(input.value);document.getElementById('budget').textContent=Number.isInteger(n)&&n>=5&&n<=15?'¥'+(Number(p.rate_cny)*n).toFixed(2)+'（日期化公开报价预算，非实测账单）':'请输入5至15的整数秒';}input.addEventListener('input',update);update();</script></main></body></html>
'''


def write_outputs(root:Path, result:dict[Path,str], check:bool=False) -> list[str]:
    changed=[]
    for relative, content in result.items():
        path=root/relative
        data=content.encode('utf-8')
        if not path.exists() or path.read_bytes()!=data:
            changed.append(str(relative))
            if not check:
                path.parent.mkdir(parents=True,exist_ok=True)
                fd,tmp=tempfile.mkstemp(dir=path.parent,prefix='.'+path.name+'.')
                try:
                    with os.fdopen(fd,'wb') as f: f.write(data)
                    os.replace(tmp,path)
                finally:
                    if os.path.exists(tmp): os.unlink(tmp)
    return changed


def main(argv:list[str]|None=None)->int:
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--check',action='store_true')
    args=ap.parse_args(argv)
    changed=write_outputs(ROOT,outputs(),args.check)
    print(('DRIFT: ' if args.check else 'Updated: ')+', '.join(changed) if changed else 'All generated outputs match their inputs.')
    return 1 if args.check and changed else 0


if __name__=='__main__':
    raise SystemExit(main())
