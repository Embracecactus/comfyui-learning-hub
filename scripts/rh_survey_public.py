"""Offline interpretation of dated anonymous official catalog/price evidence.

Raw webpage price tables are evidence, not model task results or account bills.
Only an unambiguous, exact endpoint/resolution per-second row may become a rate.
All conditional/token/fps/mode price tables remain available without flattening.
"""
from __future__ import annotations
import copy
import hashlib
import json
import re
from decimal import Decimal, ROUND_CEILING
from pathlib import Path

SOURCE_ID = 'runninghub-public-cn-20260921'
H3 = 'minimax/hailuo-h3/text-to-video'
REGEN = 'minimax/hailuo-h3/regeneration-text-to-video'
UPSCALE = 'rhart-video/video-upscaler'


def validate(snapshot: dict) -> None:
    page = snapshot['catalogue']['pagination']
    models = snapshot['models']
    if snapshot.get('authenticated') or snapshot.get('paid_task_count') != 0:
        raise ValueError('Public snapshot must not be confused with private billing')
    if page.get('hasNext') or page.get('nextCursor') or int(page['total']) != len(models):
        raise ValueError('Incomplete public catalog pagination')
    if len({m['id'] for m in models}) != len(models) or len({m['sku_id'] for m in models}) != len(models):
        raise ValueError('Duplicate public endpoint/SKU')
    known={m['sku_id'] for m in models}
    for entry in snapshot['price_tables']:
        if entry['request']['skuId'] not in known or entry.get('status')!=200 or entry['body'].get('code')!=0:
            raise ValueError('Unbound or failed price table')
    for quote in snapshot['h3_public_calculations']:
        body=quote.get('body',{})
        if quote.get('status')!=200 or body.get('code')!=0 or body.get('data',{}).get('currency')!='CNY':
            raise ValueError('A failed/non-CNY calculation cannot become a CNY quote')


def tables(snapshot:dict)->dict[str,dict]:
    return {r['request']['skuId']:r for r in snapshot['price_tables']}


def exact_rates(snapshot:dict)->list[dict]:
    result=[]
    for m in snapshot['models']:
        item=tables(snapshot).get(m['sku_id'])
        if not item:continue
        tab=item['body']['data'] or {}
        if tab.get('priceType')!='MULTI_DIMENSION':continue
        cols=[c.get('name','') for c in tab.get('columns') or []]
        if not cols or cols[0] not in ('resolution','分辨率','档位'):continue
        # A table with extra dimensions or material fees is not an unconditional total.
        conditional=bool(tab.get('conditionRows') or tab.get('conditionPrices') or tab.get('floorTable'))
        for index,row in enumerate(tab.get('rows') or []):
            cells=row['cells']
            if len(cells)<2:continue
            label=cells[0]
            target='2K' if '/regeneration-' in m['id'] and label=='768P → 2K' else label
            if target.lower() not in {r.lower() for r in m['resolution_options']}:continue
            hit=re.fullmatch(r'[¥￥]?(\d+(?:\.\d+)?)/秒',cells[1])
            if not hit:continue  # token+seconds, multiple price components, or fps dimensions
            basis='input_seconds_ceil_min5' if m['id']==UPSCALE else 'billable_output_second'
            result.append({'endpoint':m['id'],'sku_id':m['sku_id'],'resolution':target,'rate_cny':hit.group(1),
                           'unit':'CNY/'+basis,'unconditional':not conditional,
                           'verification':'official_public_table_retrieved_not_live_bill',
                           'source_id':SOURCE_ID,'observed_at':item['observed_at'][:10],
                           'source_url':m['source_url'],'source_table_row':index,
                           'constraints':{'note':cells[2] if len(cells)>2 and cells[2] not in ('true','false') else '',
                                          'condition_rows':tab.get('conditionRows'), 'condition_prices':tab.get('conditionPrices'),
                                          'floor_table':tab.get('floorTable'),'base_subtitle':tab.get('baseSubtitle')}})
    return result


def model_contracts(snapshot:dict)->list[dict]:
    result=copy.deepcopy(snapshot['models'])
    for m in result:
        m['pricing']={'status':'current_public_table_only','note':'No historical or sibling price fallback in the live catalog'}
        m['verification_status']='current_public_schema_not_run'
        m['verification_notes']=[]
        m['sources']=[m['source_url']]
    return result


def apply(evidence:dict, root:Path, doc:Path)->dict:
    result=copy.deepcopy(evidence)
    ref=evidence.get('public_snapshot')
    if not ref:return result
    path=root/doc/ref['path'];raw=path.read_bytes()
    if hashlib.sha256(raw).hexdigest()!=ref['sha256']:
        raise ValueError('Public evidence hash mismatch; reimport explicitly')
    snapshot=json.loads(raw);validate(snapshot)
    current=exact_rates(snapshot)
    identities={(p['endpoint'],p['resolution'].lower()) for p in current}
    result['platform_prices']=current+[p for p in evidence['platform_prices'] if (p['endpoint'],p['resolution'].lower()) not in identities]
    result['_public_snapshot']=snapshot
    result['_live_models']=model_contracts(snapshot)
    return result


def regeneration_budget(source_seconds:str|int, output_seconds:str|int, source_rate:str, regeneration_rate:str)->Decimal:
    a,b=Decimal(str(source_seconds)),Decimal(str(output_seconds))
    if not a.is_finite() or not b.is_finite() or min(a,b)<=0:raise ValueError('Invalid billable duration')
    return a*Decimal(source_rate)+b*Decimal(regeneration_rate)


def upscale_budget(source_billable_seconds:str|int, input_media_seconds:str, source_rate:str, upscale_rate:str)->Decimal:
    source=Decimal(str(source_billable_seconds));media=Decimal(input_media_seconds)
    if not source.is_finite() or not media.is_finite() or min(source,media)<=0:raise ValueError('Invalid duration')
    billed=max(media.to_integral_value(rounding=ROUND_CEILING),Decimal(5))
    return source*Decimal(source_rate)+billed*Decimal(upscale_rate)


def publication(snapshot:dict, historical:dict, csv_text, table, classify)->tuple[dict[Path,str],str]:
    """Generate current catalog and all explicit-2K video price-table evidence."""
    validate(snapshot);models=model_contracts(snapshot);prices=tables(snapshot)
    current={m['id'] for m in models};past={m['id'] for m in historical['model_capabilities']}
    joined=[];costs=[]
    for m in models:
        res=m['resolution_options'];video=m['output_type']=='video';two=video and '2k' in [r.lower() for r in res]
        classification=classify(m) if video else 'not_video'
        joined.append({'endpoint':m['id'],'sku_id':m['sku_id'],'name':m['name_cn'],'category':m['category'],
                       'output_type':m['output_type'],'resolutions':'|'.join(res),'explicit_2k':two,'classification':classification,
                       'presence':'in_both' if m['id'] in past else 'not_in_retained_github_snapshot',
                       'upstream_updated_at':m['upstream_updated_at'],'retrieved_at':m['observed_at'],'source_url':m['source_url']})
        if not two:continue
        raw=prices.get(m['sku_id']);tab=raw['body']['data'] if raw else None
        selected=[r['cells'] for r in (tab or {}).get('rows') or [] if any('2k' in str(c).lower() for c in r['cells'][:2])]
        notes=' '.join(str(c) for row in selected for c in row)
        nature='720p原生生成后超分（官方价表明示）' if '720p' in notes and ('放大' in notes or '超分' in notes) else ('独立视频增强/超分' if classification=='upscaler' else ('768P再生成2K' if classification=='regeneration' else '见具体契约；标签不代替像素实测'))
        costs.append({'endpoint':m['id'],'sku_id':m['sku_id'],'classification':classification,'2k_nature':nature,
                      'duration_options':'|'.join(m['duration_options']),'price_columns':json.dumps((tab or {}).get('columns'),ensure_ascii=False),'2k_price_rows':json.dumps(selected,ensure_ascii=False),
                      'additional_material_charges':json.dumps((tab or {}).get('conditionRows') or (tab or {}).get('conditionPrices'),ensure_ascii=False),
                      'minimum_billing':json.dumps((tab or {}).get('floorTable'),ensure_ascii=False),
                      'base_subtitle':(tab or {}).get('baseSubtitle'),'billing_tip':(tab or {}).get('tableTip'),
                      'source_url':m['source_url'],'retrieved_at':m['observed_at'],'evidence':'official_public_table_not_actual_bill' if raw else 'not_retrieved',
                      'actual_bill_verified':False})
    counts={'listing_total':len(models),'video_classified':sum(m['output_type']=='video' for m in models),
            'explicit_2k_video':len(costs),'direct_text_2k_candidates':sum(r['classification']=='direct_text' for r in costs),
            'target_tables_obtained':sum(r['evidence']=='official_public_table_not_actual_bill' for r in costs),
            'public_tables_downloaded_all_types':len(snapshot['price_tables']),
            'added_vs_github_snapshot':len(current-past),'github_snapshot_not_in_this_view':len(past-current)}
    delta={'scope':snapshot['catalogue'],'counts':counts,'added_vs_github_snapshot':sorted(current-past),
           'github_snapshot_not_in_this_view':sorted(past-current),'note':'Different source scopes; absence is NOT a deprecation or removal claim.'}
    qrows=[]
    for q in snapshot['h3_public_calculations']:
        factors={p['fieldKey']:p['fieldValue'] for p in q['request']['priceFactors']}
        data=q['body']['data'];qrows.append([factors['resolution'],factors['duration'],data['estimatedPrice'],data['currency'],'匿名网页报价；非企业扣费'])
    report='# 2026-09-21 官方公开报价与目录复核\n\n'
    report+='采集范围：中国站匿名 STANDARD_MODEL 列表、SKU详情及网页价格表。使用公开只读端点，不使用API Key、不创建任务、不下单。网页报价接口不等于开发者标准API price-preview，亦不证明企业账户折扣或实际扣费。\n\n'
    report+=table(['核验项','结果'],list(counts.items()))+'\n\n'
    report+='SSR请求 pageNum=1/pageSize=999，返回 total=244、records=244、pages=1、hasNext=false；逐SKU详情244/244成功。已对齐唯一SKU和endpoint，没有按首页宣传数量推算覆盖率。保留的GitHub 422模型与353条旧价格文件本轮重新下载哈希不变，但不代表它们与网站实时目录相同。差集见data/live-catalog-diff.json，不把未列出推断为下架。\n\n'
    report+='## H3 当前匿名公开报价\n\n'+table(['档位','输出秒','CNY报价','币种','证据'],qrows)+'\n\n'
    report+='## 两阶段报价已查到，实际账单仍需执行\n\n文生H3的768P为¥0.48/计费输出秒；文生regeneration为¥0.30/再生成输出秒。文生再生成价表没有第二笔baseVideo输入费，不能把多模态参考素材的重计费套用到生成好的源视频。\n\n`预算 = 0.48 × 阶段1计费秒 + 0.30 × 阶段2计费输出秒`。仅当两个阶段分别按5/10/15秒计费时，对应¥3.90/¥7.80/¥11.70。历史5秒请求的媒体实际5.167秒；阶段2实际计费秒和舍入未实测，不能把以上预算称为实扣总价。源提示词须为实际最终模型提示词，且保留同源taskId/哈希链。\n\n多模态H3另外按输入参考视频秒收费：生成2K/768P各为¥0.77/¥0.48每输入秒；图片超过5张的部分¥0.20/张。多模态再生成重计原任务参考视频¥0.30/输入秒、超过5张图片¥0.15/张；音频免费。此处的“原任务输入素材”不是一律给生成源视频额外加费。\n\n'
    report+='## 普通超分的计费取整\n\nRH视频超分2K为¥0.35/秒，官方价表明确 `max(ceil(输入媒体秒),5)`。5.167秒源片按6秒预算，超分部分¥2.10；若阶段1按5秒计费¥2.40，则合计预算¥4.50，不是按5秒超分得到的¥4.15。实际账单仍未核验；普通超分不冒充原生2K或H3 regeneration。\n\n'
    report+='## 所有2K标签视频条目的价表\n\n'+table(['端点','调用性质','2K性质','价表2K行（附加费/完整结构见CSV与JSON）'],[[r['endpoint'],r['classification'],r['2k_nature'],r['2k_price_rows']] for r in costs])+'\n\n'
    report+='Seedance2.5文生2K不是固定每秒总价：按completion tokens的¥87.5/百万tokens加¥0.42/输出秒；不能只报超分的¥0.42。提示词增强H3-Context-IR也另按输入/输出token收费，免费/skip模式与收费模式须区分。新增视频增强端点保留模式与帧率档，不选择最便宜行冒充默认价格。\n\n'
    report+='## 实际尝试后的剩余条件\n\n本地未提供RH凭据；CI仅检查RH_API_KEY及RH_ENTERPRISE_API_KEY两个约定Secret输入，均为空（不代表枚举了全部仓库Secrets）。本轮私人任务查询0、付费任务0。企业实扣、两阶段账单、个人10/15秒币费仍无法生成；也未从文件库找到相应原始账单。\n\n会员入口实际跳转SSO登录；企业独占、共享控制台和完整节点费页也需登录。RH币购买/会员账单及独占GPU正式租价仍需授权登录资料，不采用第三方代充或默认币兑元比例。会员固定费摊销、实际产量和失败成本不得计零。\n\n'
    report+='## 可复核来源\n\n来源及方法见data/public-pricing-20260921.json，其中保留目录分页、244份精确schema、60份公开价表、6次H3报价、采集时间、原始文件哈希和Actions采集版本。生成数据由统一构建入口检查。\n\n采集运行：'+snapshot['provenance']['workflow_run']+'\n'
    result={Path('data/live-model-capabilities.csv'):csv_text(joined),Path('data/live-2k-price-tables.csv'):csv_text(costs),
            Path('data/live-catalog-diff.json'):json.dumps(delta,ensure_ascii=False,indent=1)+'\n',
            Path('06-公开报价与目录复核.md'):report}
    summary=f"当前匿名中国站目录{len(models)}项，显式2K视频{len(costs)}项，目标价表{counts['target_tables_obtained']}/{len(costs)}已取得；与保留的GitHub快照分列，见06-公开报价与目录复核.md。"
    return result,summary
