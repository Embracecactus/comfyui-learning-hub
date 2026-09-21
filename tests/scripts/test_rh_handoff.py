"""Offline handoff regression tests; no keys, network, model files or paid tasks."""
import contextlib
import copy
import importlib.util
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'scripts'))
sys.path.insert(0, str(ROOT / 'docs/05-RunningHub-API/examples/python'))
import rh_survey_handoff as gen
import rh_survey_build_registry as builder
import rh_min_client as client
import rh_evidence_audit as audit


class GenerationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.e = gen.load(ROOT/gen.DOC/'data/handoff-evidence.json')
        cls.r = gen.load(ROOT/gen.DOC/'data/runninghub-api-registry.json')

    def test_generated_outputs_match(self):
        self.assertEqual(gen.write_outputs(ROOT, gen.outputs(), check=True), [])

    def test_normalization_idempotent(self):
        a = gen.normalize(self.r, self.e)
        self.assertEqual(a, gen.normalize(a, self.e))

    def test_exact_h3_prices(self):
        rows = gen.cost_rows(self.r, self.e, '2K')
        h = next(x for x in rows if x['route_id']=='standard:'+gen.H3+':2K')
        self.assertEqual([h[k] for k in ('five_second_cost','ten_second_cost','fifteen_second_cost')], ['¥3.85','¥7.70','¥11.55'])
        rows = gen.cost_rows(self.r, self.e, '768P')
        h = next(x for x in rows if x['route_id']=='standard:'+gen.H3+':768P')
        self.assertEqual(h['five_second_cost'], '¥2.40')

    def test_single_source_price_change(self):
        e = copy.deepcopy(self.e)
        next(p for p in e['platform_prices'] if p['resolution']=='2K')['rate_cny']='1.23'
        h = next(x for x in gen.cost_rows(self.r,e,'2K') if x['route_id']=='standard:'+gen.H3+':2K')
        self.assertEqual(h['five_second_cost'],'¥6.15')

    def test_no_family_price_propagation(self):
        for ep in ('minimax/hailuo-h3/image-to-video',gen.REGEN):
            model=next(m for m in self.r['model_capabilities'] if m['id']==ep)
            self.assertIsNone(gen.rate(model,'2K',self.e)['cny'])

    def test_all_video_endpoints_classified(self):
        r=gen.normalize(self.r,self.e)
        videos=[m for m in r['model_capabilities'] if m.get('output_type')=='video']
        self.assertEqual(len(videos),228)
        self.assertEqual(sum(m['supports_2k'] for m in videos),22)
        self.assertEqual(sum(m['single_prompt_2k']=='direct_text' for m in videos),5)
        self.assertTrue(all(m['single_prompt_2k'] in gen.LABELS for m in videos))

    def test_two_stage_no_fabricated_total(self):
        rows=[r for r in gen.cost_rows(self.r,self.e,'2K') if r['route_class'].startswith('two-stage')]
        self.assertEqual(len(rows),2)
        self.assertTrue(all(r['five_second_cost']=='未核验' and r['full_cost_status']=='incomplete' for r in rows))

    def test_personal_not_enterprise_evidence(self):
        r=gen.normalize(self.r,self.e)
        self.assertEqual(len([x for x in r['run_evidence'] if x['route']=='personal-ai-app']),3)
        self.assertFalse(any(x.get('key_type')=='enterprise-shared' for x in r['run_evidence']))

    def test_drift_detection_does_not_write(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d)
            p=Path('example.txt')
            (root/p).write_text('old')
            self.assertEqual(gen.write_outputs(root,{p:'new'},True),['example.txt'])
            self.assertEqual((root/p).read_text(),'old')

    def test_duplicate_model_fails(self):
        r=copy.deepcopy(self.r)
        r['model_capabilities'].append(r['model_capabilities'][0])
        with self.assertRaises(ValueError): gen.normalize(r,self.e)

    def test_refresh_hash_is_actual(self):
        raw=json.dumps([{'endpoint':'test/model','params':[],'output_type':'video'}]).encode()
        r=builder.refresh(copy.deepcopy(self.r),raw,'test-local')
        import hashlib
        self.assertEqual(r['meta']['freshness']['model_sha256'],hashlib.sha256(raw).hexdigest())
        self.assertEqual(r['model_capabilities'][0]['pricing']['status'],'no_public_price')

    def test_refresh_rejects_empty_truncated_duplicate(self):
        for raw in (b'[]',b'{',b'[{"endpoint":"x","params":[]},{"endpoint":"x","params":[]}]'):
            with self.subTest(raw=raw), self.assertRaises(ValueError):
                builder.refresh(copy.deepcopy(self.r),raw,'test')

    def test_default_builder_is_offline(self):
        with patch('urllib.request.urlopen',side_effect=AssertionError('network forbidden')):
            self.assertEqual(builder.main(['--check']),0)

    def test_no_upstream_anchor_in_cost_outputs(self):
        for path in ('data/cost-2k.csv','data/cost-768p.csv'):
            text=(ROOT/gen.DOC/path).read_text()
            self.assertNotIn('platform.minimax',text)
            self.assertNotIn('充值即恢复',text)


class ClientTests(unittest.TestCase):
    def setUp(self):
        self.c=client.RunningHubClient(api_key='test-credential-not-real')
        self.stdout=contextlib.redirect_stdout(io.StringIO()); self.stdout.__enter__()
        self.stderr=contextlib.redirect_stderr(io.StringIO()); self.stderr.__enter__()

    def tearDown(self):
        self.stdout.__exit__(None,None,None); self.stderr.__exit__(None,None,None)

    def test_account_lowercase_contract(self):
        with patch.object(client,'_request',return_value={'code':0,'data':{}}) as req:
            self.c.account_status()
        self.assertTrue(req.call_args.args[0].endswith('/uc/openapi/accountStatus'))
        self.assertEqual(req.call_args.args[2],{'apikey':self.c.key})

    def test_account_cli(self):
        with patch.object(client.RunningHubClient,'account_status',return_value={'code':0}) as call:
            self.assertEqual(client.main(['account']),0)
            call.assert_called_once()

    def test_flat_and_wrapped_task_ids(self):
        for response in ({'taskId':'1','errorCode':''},{'code':0,'data':{'taskId':'2'}},{'task_id':'3'}):
            with patch.object(client,'_request',return_value=response) as req:
                self.assertIn(self.c.submit('x',{}),('1','2','3'))
                self.assertEqual(req.call_args.kwargs['retries'],1)

    def test_business_error_not_success(self):
        for response in ({'errorCode':'1014'}, {'code':421,'msg':'queue'}, {'code':0,'data':{'errorCode':416}}):
            with patch.object(client,'_request',return_value=response),self.assertRaises(client.RHError):
                self.c.submit('x',{})

    def test_missing_task_id_is_uncertain(self):
        with patch.object(client,'_request',return_value={'code':0}),self.assertRaises(client.SubmissionUncertain):
            self.c.submit('x',{})

    def test_malformed_json_response_is_uncertain(self):
        with patch.object(client,'_request',return_value=[]),self.assertRaises(client.SubmissionUncertain):
            self.c.submit('x',{})

    def test_all_submit_channels_use_one_attempt(self):
        for call in (lambda:self.c.submit('x',{}),lambda:self.c.ai_app_run('1',[]),lambda:self.c.workflow_create('1')):
            with patch.object(client,'_request',side_effect=client.TransportError('network gone')) as req:
                with self.assertRaises(client.SubmissionUncertain): call()
                req.assert_called_once()

    def test_uncertain_persisted_for_every_route(self):
        for kind in ('standard','ai-app','workflow'):
            with tempfile.TemporaryDirectory() as d, patch.object(client,'_request',side_effect=client.TransportError('lost')):
                with patch.object(self.c,'price_preview',return_value={'estimatedPrice':3.85,'currency':'CNY'}):
                    with self.assertRaises(client.SubmissionUncertain):
                        if kind=='standard': self.c.run('x',{},execute=True,record_dir=Path(d))
                        elif kind=='ai-app': self.c.run_ai_app('1',[],execute=True,record_dir=Path(d))
                        else: self.c.run_workflow('1',[],execute=True,record_dir=Path(d))
                files=list(Path(d).rglob('task_record.json'))
                self.assertEqual(len(files),1)
                self.assertEqual(json.loads(files[0].read_text())['status'],'SUBMISSION_UNCERTAIN')

    def test_price_error_blocks_paid_submission(self):
        with patch.object(self.c,'price_preview',side_effect=client.RHError('1014')),patch.object(self.c,'submit') as submit:
            with self.assertRaises(client.RHError): self.c.run('x',{},execute=True)
            submit.assert_not_called()

    def test_missing_price_blocks_paid_submission(self):
        with patch.object(self.c,'price_preview',return_value={}),patch.object(self.c,'submit') as submit:
            with self.assertRaises(client.RHError): self.c.run('x',{},execute=True)
            submit.assert_not_called()

    def test_dry_runs_do_not_network(self):
        with patch.object(client,'_request',side_effect=AssertionError('network forbidden')):
            self.assertEqual(self.c.run('x',{})['status'],'DRY_RUN')
            self.assertEqual(self.c.run_ai_app('1',[])['status'],'DRY_RUN')
            self.assertEqual(self.c.run_workflow('1',[])['status'],'DRY_RUN')
            self.assertEqual(client.main(['video','--key-type','consumer-member','--prompt','猫']),0)

    def test_single_prompt_enterprise_string_duration(self):
        with patch.object(client.RunningHubClient,'run',return_value={'status':'DRY_RUN'}) as run:
            client.main(['video','--key-type','enterprise-shared','--prompt','猫','--duration','6'])
            self.assertEqual(run.call_args.args[1]['duration'],'6')
            self.assertFalse(run.call_args.kwargs['execute'])

    def test_single_prompt_personal_channel(self):
        with patch.object(client.RunningHubClient,'run_ai_app',return_value={'status':'DRY_RUN'}) as run:
            client.main(['video','--key-type','consumer-member','--prompt','猫'])
            self.assertEqual(run.call_args.args[0],'2083105376052006914')
            self.assertEqual(next(x['fieldValue'] for x in run.call_args.args[1] if x['fieldName']=='resolution'),'2K')

    def test_duration_and_empty_prompt_rejected(self):
        with self.assertRaises(SystemExit): client.main(['video','--key-type','consumer-member','--prompt','猫','--duration','4'])
        with self.assertRaises(client.RHError): client.main(['video','--key-type','consumer-member','--prompt',' '])

    def test_inline_and_workflow_id_mutually_exclusive(self):
        with self.assertRaises(SystemExit): client.main(['run-workflow','123','--inline','x.json'])

    def test_query_unwrap_and_errors(self):
        with patch.object(client,'_request',return_value={'code':0,'data':{'status':'SUCCESS'}}):
            self.assertEqual(self.c.query('1')['status'],'SUCCESS')
        with patch.object(client,'_request',return_value={'code':0}),self.assertRaises(client.RHError): self.c.query('1')

    def test_redacts_nested_key_and_error_url(self):
        body={'data':{'apiKey':'secret'},'text':self.c.key+'?apiKey=other&x=1'}
        text=json.dumps(client.redact(body,self.c.key))
        self.assertNotIn('secret',text); self.assertNotIn('other',text); self.assertNotIn(self.c.key,text)

    def test_resume_download_failure_not_success(self):
        with patch.object(self.c,'query',return_value={'status':'SUCCESS'}),patch.object(self.c,'archive_outputs',return_value=[{'download_error':'x'}]):
            self.assertEqual(client.build_record_from_existing(self.c,'1',Path('/unused'))['status'],'OUTPUT_INCOMPLETE')

    def test_media_probe_error_not_validated(self):
        with tempfile.TemporaryDirectory() as d,patch.object(self.c,'poll',return_value={'status':'SUCCESS'}),patch.object(self.c,'archive_outputs',return_value=[{'media':{'error':'ffprobe missing'}}]):
            record={'task_id':'1','status':'SUBMITTED','transitions':[],'errors':[]}
            self.assertEqual(self.c._finish(record,Path(d))['status'],'OUTPUT_INCOMPLETE')


class AuditTests(unittest.TestCase):
    def setUp(self):
        self.media={'width':1344,'height':768,'fps':24,'frames':124,'has_audio':True,'format_name':'mov,mp4'}
        self.source={'task_id':'a','endpoint':gen.H3,'status':'SUCCESS','final_model_prompt':'final prompt'}
        charge=lambda id,amount:{'charge_id':id,'source_field':'usage.modelFee','scope':'disjoint_charge','unit':'CNY','amount':amount}
        self.a={'task_id':'a','endpoint':gen.H3,'status':'SUCCESS','final_prompt_sha256':'prompt-hash','output_sha256':'media-hash','billing_complete':True,'cost_components':[charge('a:fee','2.40')]}
        self.b={'task_id':'b','endpoint':gen.REGEN,'status':'SUCCESS','source_task_id':'a','final_prompt_sha256':'prompt-hash','source_sha256':'media-hash','billing_complete':True,'cost_components':[charge('b:fee','3.00')]}

    def test_missing_key_no_network(self):
        c=client.RunningHubClient(); c.key=''
        with patch.object(c,'query') as q,patch.object(c,'price_preview') as p:
            result,code=audit.capture(['1'],[],c)
            self.assertEqual(result['status'],'blocked_missing_key'); self.assertEqual(code,2)
            q.assert_not_called();p.assert_not_called()

    def test_quote_not_bill(self):
        c=Mock(key='fake');c.price_preview.return_value={'estimatedPrice':3.85,'currency':'CNY'}
        result,code=audit.capture([], [{'endpoint':gen.H3,'payload':{'prompt':'private'}}],c)
        self.assertEqual(code,0);self.assertEqual(result['quotes'][0]['status'],'quoted_not_billed')
        self.assertNotIn('private',json.dumps(result));c.submit.assert_not_called()

    def test_regen_quote_requires_validated_source(self):
        c=Mock(key='fake')
        result,code=audit.capture([], [{'endpoint':gen.REGEN,'payload':{}}],c)
        self.assertEqual(code,2);c.price_preview.assert_not_called()

    def test_query_ids_deduplicated(self):
        c=Mock(key='fake');c.query.return_value={'status':'SUCCESS'}
        audit.capture(['1','1'],[],c);c.query.assert_called_once_with('1')

    def test_source_constraints_pass(self):
        self.assertEqual(audit.validate_source(self.media,self.source,'final prompt')['status'],'passed')

    def test_final_prompt_exact_match_required(self):
        self.assertEqual(audit.validate_source(self.media,self.source,'final prompt\n')['status'],'blocked')

    def test_invalid_source_constraints(self):
        for change in ({'width':2560},{'fps':30},{'has_audio':False},{'frames':106},{'format_name':'webm'}):
            with self.subTest(change=change):
                self.assertEqual(audit.validate_source({**self.media,**change},self.source,'final prompt')['status'],'blocked')

    def test_cloud_workflow_not_assumed_regen_equivalent(self):
        self.source['endpoint']='workflow:open-h3'
        self.assertEqual(audit.validate_source(self.media,self.source,'final prompt')['status'],'blocked')

    def test_reconcile_synthetic_known_charges(self):
        r=audit.reconcile(self.a,self.b)
        self.assertEqual(r['status'],'reconciled');self.assertEqual(r['complete_totals']['CNY'],'5.40')

    def test_reconcile_duplicate_is_not_charged_twice(self):
        self.b['cost_components'].append(copy.deepcopy(self.b['cost_components'][0]))
        self.assertEqual(audit.reconcile(self.a,self.b)['complete_totals']['CNY'],'5.40')

    def test_reconcile_conflict_blocks(self):
        self.b['cost_components'].append({**self.b['cost_components'][0],'amount':'4.00'})
        self.assertIsNone(audit.reconcile(self.a,self.b)['complete_totals'])

    def test_null_is_not_zero(self):
        self.b['cost_components'][0]['amount']=None
        self.assertEqual(audit.reconcile(self.a,self.b)['status'],'incomplete')

    def test_chain_aggregates_not_summed(self):
        self.b['cost_components'][0]['scope']='parent_total'
        self.assertIsNone(audit.reconcile(self.a,self.b)['complete_totals'])

    def test_coins_not_implicitly_cny(self):
        self.b['cost_components'].append({'charge_id':'b:coins','scope':'disjoint_charge','source_field':'usage.consumeCoins','unit':'RH_coin','amount':'5'})
        result=audit.reconcile(self.a,self.b)
        self.assertEqual(result['status'],'reconciled');self.assertIsNone(result['total_cny_including_coins'])

    def test_broken_stage_links_rejected(self):
        for field in ('source_task_id','source_sha256','final_prompt_sha256'):
            b={**self.b,field:'wrong'}
            self.assertEqual(audit.reconcile(self.a,b)['status'],'incomplete')

    def test_incomplete_bill_does_not_become_complete(self):
        self.a['billing_complete']=False
        self.assertIsNone(audit.reconcile(self.a,self.b)['complete_totals'])

    def test_signed_urls_omitted(self):
        output=audit.safe_capture({'url':'https://example.com/file?sig=private','apiKey':'secret'},'secret')
        self.assertNotIn('sig=private',json.dumps(output));self.assertNotIn('secret',json.dumps(output))

if __name__=='__main__': unittest.main()
