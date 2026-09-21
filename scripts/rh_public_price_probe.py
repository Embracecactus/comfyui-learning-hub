#!/usr/bin/env python3
"""Read anonymous RunningHub price pages without tasks, orders or account APIs.
Playwright is an optional research dependency, not required by normal clients.
Outputs are gitignored. Publication must retain source/scope and redact private data.
"""
import asyncio
import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit
from playwright.async_api import async_playwright

OUT=Path('output/public-probe')
ORIGIN='https://www.runninghub.cn'
READ_PATHS={'/api/sku/detail','/api/area/price/table','/api/area/price/calculate'}
DETAIL_KEYS=('id','categoryType','language','isOversea','name','nameEn','rhEndpoint','description','descriptionEn','modelHighlights','modelHighlightsEn','inputConfigJson','createTime','updateTime','relationTags','instanceType')

def save(name,obj):
    raw=(json.dumps(obj,ensure_ascii=False,indent=2)+'\n').encode()
    (OUT/name).write_bytes(raw)
    return hashlib.sha256(raw).hexdigest()

def decode_nuxt(data,index):
    """Decode the public SSR devalue reference table; reject unknown wrappers."""
    if index<0:return None
    value=data[index]
    if isinstance(value,dict):return {k:decode_nuxt(data,v) for k,v in value.items()}
    if isinstance(value,list):
        if value and isinstance(value[0],str):
            if value[0] in ('Reactive','ShallowReactive','Ref','ShallowRef') and len(value)==2:return decode_nuxt(data,value[1])
            raise ValueError('Unsupported SSR wrapper: '+str(value[0]))
        return [decode_nuxt(data,v) for v in value]
    return value

async def main():
    OUT.mkdir(parents=True,exist_ok=True)
    captured=[]; pending=[]; ids=set(); pages=[]; catalogues=[]
    async with async_playwright() as p:
        browser=await p.chromium.launch()
        ctx=await browser.new_context(locale='zh-CN',viewport={'width':1440,'height':1000})
        async def record(resp):
            path=urlsplit(resp.url).path
            if urlsplit(resp.url).netloc!='www.runninghub.cn':return
            if not any(x in path.lower() for x in ('sku','price','member','product','package','goods','vip','recharge','rental')):return
            if any(x in path.lower() for x in ('order','account','userinfo','login','token','history')):return
            if 'json' not in resp.headers.get('content-type',''):return
            try:
                body=await resp.json()
                if path=='/api/sku/detail' and isinstance(body.get('data'),dict):
                    body={**body,'data':{k:v for k,v in body['data'].items() if k in DETAIL_KEYS}}
                captured.append({'url':resp.url,'method':resp.request.method,'status':resp.status,'request':resp.request.post_data_json if resp.request.post_data else None,'body':body})
            except Exception:pass
        ctx.on('response',lambda r:pending.append(asyncio.create_task(record(r))))
        for name,path in [('fees','/third-party-fees'),('catalog','/call-api/search-api/standard-model'),('h3-price','/call-api/api-detail/2133100000000504202')]:
            page=await ctx.new_page();entry={'name':name,'url':ORIGIN+path}
            try:
                await page.goto(entry['url'],wait_until='domcontentloaded',timeout=65000)
                await page.wait_for_timeout(4000)
                if name=='catalog':
                    data=json.loads(await page.locator('#__NUXT_DATA__').inner_text())
                    for item in data:
                        if not isinstance(item,dict):continue
                        for key,index in item.items():
                            if key.startswith('api-list-search-STANDARD_MODEL-'):
                                value=decode_nuxt(data,index)
                                cat={'cache_key':key,'url':page.url,**value};catalogues.append(cat)
                                records=cat['page']['records']
                                if len(records)!=int(cat['page']['total']) or cat['page'].get('hasNext'):
                                    raise ValueError('Incomplete catalog; no full coverage claim allowed')
                                ids.update(str(r['id']) for r in records)
                                print('CATALOG',len(records),'total',cat['page']['total'],'hasNext',cat['page'].get('hasNext'))
                if name=='h3-price':
                    tab=page.get_by_text('价格',exact=True)
                    if await tab.count()>1:await tab.last.click(timeout=5000);await page.wait_for_timeout(1500)
                text=await page.locator('body').inner_text()
                (OUT/(name+'.txt')).write_text(text,encoding='utf-8')
                (OUT/(name+'.html')).write_text(await page.content(),encoding='utf-8')
                entry['text_sha256']=hashlib.sha256(text.encode()).hexdigest();entry['resolved_url']=page.url
                entry['links']=await page.locator('a[href]').evaluate_all('(e)=>e.map(x=>({text:x.innerText,url:x.href}))')
                await page.screenshot(path=str(OUT/(name+'.png')),full_page=True)
                print(name,len(text),'text chars')
                if name=='h3-price':
                    member=page.get_by_text('开通会员',exact=True)
                    if await member.count():
                        old=set(ctx.pages)
                        await member.first.click(timeout=5000);await page.wait_for_timeout(5000)
                        targets=[x for x in ctx.pages if x not in old] or [page]
                        for i,target in enumerate(targets):
                            await target.wait_for_load_state('domcontentloaded',timeout=30000);await target.wait_for_timeout(5000)
                            name2=f'member-{i}';text=await target.locator('body').inner_text()
                            (OUT/(name2+'.txt')).write_text(text,encoding='utf-8')
                            (OUT/(name2+'.html')).write_text(await target.content(),encoding='utf-8')
                            await target.screenshot(path=str(OUT/(name2+'.png')),full_page=True)
                            pages.append({'name':name2,'url':target.url,'text_sha256':hashlib.sha256(text.encode()).hexdigest()})
                            print('MEMBER PAGE',target.url,text[:7000])
                            if target!=page:await target.close()
            except Exception as e:entry['error']=str(e)[:200]
            pages.append(entry);await page.close()
        if pending:await asyncio.gather(*pending,return_exceptions=True)
        save('observed-responses.json',captured);save('pages.json',pages);save('catalogues.json',catalogues)
        print('Observed paths',sorted({urlsplit(x['url']).path for x in captured}))
        ids.add('2133100000000504202')
        async def post(path,payload):
            if path not in READ_PATHS:raise ValueError('Not an allowlisted read endpoint')
            resp=await ctx.request.post(ORIGIN+path,data=payload,timeout=30000)
            return {'url':ORIGIN+path,'request':payload,'status':resp.status,'observed_at':datetime.now(timezone.utc).isoformat(),'body':await resp.json()}
        details=[];tables=[];sem=asyncio.Semaphore(3)
        async def inspect(sku):
            async with sem:
                try:
                    detail=await post('/api/sku/detail',{'id':sku})
                    obj=detail['body'].get('data') or {}
                    detail['body']['data']={k:v for k,v in obj.items() if k in DETAIL_KEYS}
                    details.append(detail)
                    desc=json.dumps(detail['body'],ensure_ascii=False).lower()
                    if any(w in desc for w in ('2k','768p','hailuo-h3','h3-max','video-upscaler')):
                        tables.append(await post('/api/area/price/table',{'skuId':sku}))
                    await asyncio.sleep(.2)
                except Exception as e:details.append({'sku_id':sku,'error':type(e).__name__+': '+str(e)[:160]})
        await asyncio.gather(*(inspect(sku) for sku in sorted(ids)))
        details.sort(key=lambda x:str(x.get('request',{}).get('id',x.get('sku_id'))));tables.sort(key=lambda x:x['request']['skuId'])
        save('sku-details.json',details);save('price-tables.json',tables)
        quotes=[]
        for resolution in ('768P','2K'):
            for seconds in (5,10,15):
                payload={'skuId':'2133100000000504202','priceFactors':[{'fieldKey':'prompt','fieldValue':'一只橙猫在雨后的屋顶缓慢行走。','type':'STRING'},{'fieldKey':'resolution','fieldValue':resolution,'type':'LIST'},{'fieldKey':'duration','fieldValue':str(seconds),'type':'LIST'},{'fieldKey':'ratio','fieldValue':'16:9','type':'LIST'},{'fieldKey':'aigc_watermark','fieldValue':False,'type':'BOOLEAN'}]}
                try:quotes.append(await post('/api/area/price/calculate',payload))
                except Exception as e:quotes.append({'request':payload,'error':str(e)[:160]})
        save('h3-quotes.json',quotes)
        save('index.json',{'collected_at':datetime.now(timezone.utc).isoformat(),'authenticated':False,'paid_requests':0,'sku_ids':sorted(ids),'detail_count':len(details),'price_table_count':len(tables),'coverage':'CN anonymous STANDARD_MODEL listing only; SSR total/hasNext validated; not private/community apps, other regions or all historical endpoints','files':{f.name:hashlib.sha256(f.read_bytes()).hexdigest() for f in OUT.iterdir() if f.is_file() and f.name!='index.json'}})
        print('RESULT',len(ids),'IDs',len(tables),'tables',len(quotes),'quotes')
        await browser.close()

if __name__=='__main__':asyncio.run(main())
