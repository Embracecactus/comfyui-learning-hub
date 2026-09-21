#!/usr/bin/env python3
"""Read anonymous RunningHub pages. Never submit models, orders or private APIs.
Requires Playwright only for this explicit research command (not normal clients).
Raw research output is gitignored; curate public evidence before publishing.
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

async def main():
    OUT.mkdir(parents=True,exist_ok=True)
    captured=[]; pending=[]; ids=set(); pages=[]
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
                request=resp.request.post_data_json if resp.request.post_data else None
                item={'url':resp.url,'method':resp.request.method,'status':resp.status,'request':request,'body':body}
                captured.append(item)
            except Exception:pass
        ctx.on('response',lambda r:pending.append(asyncio.create_task(record(r))))
        for name,path in [('fees','/third-party-fees'),('catalog','/call-api/search-api/standard-model'),('h3-price','/call-api/api-detail/2133100000000504202')]:
            page=await ctx.new_page();entry={'name':name,'url':ORIGIN+path}
            try:
                await page.goto(entry['url'],wait_until='domcontentloaded',timeout=65000)
                await page.wait_for_timeout(5000)
                if name=='h3-price':
                    tab=page.get_by_text('价格',exact=True)
                    if await tab.count()>1:
                        await tab.last.click(timeout=5000);await page.wait_for_timeout(2000)
                if name=='catalog':
                    unchanged=0;last=0
                    for n in range(45):
                        await page.mouse.wheel(0,2500);await page.wait_for_timeout(800)
                        links=await page.locator('a[href]').evaluate_all('(e)=>e.map(x=>x.href)')
                        for u in links:
                            m=re.search(r'/api-detail/(\d+)',u)
                            if m:ids.add(m.group(1))
                        if len(ids)==last:unchanged+=1
                        else:unchanged=0
                        last=len(ids)
                        if unchanged>=6:break
                    entry['buttons']=await page.locator('button').all_text_contents()
                text=await page.locator('body').inner_text()
                (OUT/(name+'.txt')).write_text(text,encoding='utf-8')
                (OUT/(name+'.html')).write_text(await page.content(),encoding='utf-8')
                entry['text_sha256']=hashlib.sha256(text.encode()).hexdigest()
                entry['resolved_url']=page.url
                entry['links']=await page.locator('a[href]').evaluate_all('(e)=>e.map(x=>({text:x.innerText,url:x.href}))')
                for link in entry['links']:
                    m=re.search(r'/api-detail/(\d+)',link['url'])
                    if m:ids.add(m.group(1))
                await page.screenshot(path=str(OUT/(name+'.png')),full_page=True)
                print(name,'text bytes',len(text),'IDs',len(ids));print(text[:6500])
                if name=='h3-price':
                    member=page.get_by_text('开通会员',exact=True)
                    if await member.count():
                        await member.first.click(timeout=5000);await page.wait_for_timeout(4000)
                        (OUT/'member-dialog.txt').write_text(await page.locator('body').inner_text(),encoding='utf-8')
                        (OUT/'member-dialog.html').write_text(await page.content(),encoding='utf-8')
                        await page.screenshot(path=str(OUT/'member-dialog.png'),full_page=True)
            except Exception as e:entry['error']=str(e)[:200]
            pages.append(entry);await page.close()
        if pending:await asyncio.gather(*pending,return_exceptions=True)
        save('observed-responses.json',captured)
        save('pages.json',pages)
        print('Observed paths',sorted({urlsplit(x['url']).path for x in captured}))
        ids.add('2133100000000504202')
        # Read only observed public frontend endpoints; no model submission path.
        async def post(path,payload):
            if path not in READ_PATHS:raise ValueError('not a read-only allowlisted endpoint')
            resp=await ctx.request.post(ORIGIN+path,data=payload,timeout=30000)
            body=await resp.json()
            return {'url':ORIGIN+path,'request':payload,'status':resp.status,'body':body}
        details=[];tables=[]
        for sku in sorted(ids)[:800]:
            try:
                detail=await post('/api/sku/detail',{'id':sku})
                obj=detail['body'].get('data') or {}
                detail['body']['data']={k:v for k,v in obj.items() if k in DETAIL_KEYS}
                details.append(detail)
                desc=json.dumps(detail['body'],ensure_ascii=False).lower()
                if any(w in desc for w in ('2k','768p','hailuo-h3','h3-max','video-upscaler')):
                    tables.append(await post('/api/area/price/table',{'skuId':sku}))
                await asyncio.sleep(.12)
            except Exception as e:details.append({'sku_id':sku,'error':str(e)[:160]})
        save('sku-details.json',details);save('price-tables.json',tables)
        quotes=[]
        for resolution in ('768P','2K'):
            for seconds in (5,10,15):
                payload={'skuId':'2133100000000504202','priceFactors':[{'fieldKey':'prompt','fieldValue':'一只橙猫在雨后的屋顶缓慢行走。','type':'STRING'},{'fieldKey':'resolution','fieldValue':resolution,'type':'LIST'},{'fieldKey':'duration','fieldValue':str(seconds),'type':'LIST'},{'fieldKey':'ratio','fieldValue':'16:9','type':'LIST'},{'fieldKey':'aigc_watermark','fieldValue':False,'type':'BOOLEAN'}]}
                try:quotes.append(await post('/api/area/price/calculate',payload))
                except Exception as e:quotes.append({'request':payload,'error':str(e)[:160]})
        save('h3-quotes.json',quotes)
        save('index.json',{'collected_at':datetime.now(timezone.utc).isoformat(),'authenticated':False,'paid_requests':0,'sku_ids':sorted(ids),'detail_count':len(details),'price_table_count':len(tables),'coverage':'anonymous rendered catalog; pagination must be audited before calling it complete','files':{f.name:hashlib.sha256(f.read_bytes()).hexdigest() for f in OUT.iterdir() if f.is_file() and f.name!='index.json'}})
        print('RESULT',len(ids),'IDs',len(tables),'price tables',len(quotes),'quotes')
        await browser.close()

if __name__=='__main__':asyncio.run(main())
