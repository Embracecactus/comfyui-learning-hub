"""Offline assertions on real public captures; synthetic arithmetic is not billing."""
import copy
import hashlib
import json
from decimal import Decimal
from pathlib import Path
import sys
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'scripts'))
import rh_survey_public as public
import rh_survey_handoff as gen

class PublicEvidenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.e=gen.load_evidence(ROOT)
        cls.s=cls.e['_public_snapshot']
        cls.models={m['id']:m for m in cls.e['_live_models']}
        cls.r=gen.load(ROOT/gen.DOC/'data/runninghub-api-registry.json')

    def test_public_examples_do_not_publish_signed_credentials(self):
        import re
        raw=json.dumps(self.s,ensure_ascii=False)
        self.assertIsNone(re.search(r'\b(?:AKID|AKIA|ASIA)[A-Za-z0-9]{12,}\b',raw))
        self.assertGreater(self.s['sanitization']['changed_string_fields'],0)
        self.assertNotIn('q-signature=',raw)

    def test_snapshot_hash_and_validation(self):
        public.validate(self.s)
        metadata=gen.load(ROOT/gen.DOC/'data/handoff-evidence.json')['public_snapshot']
        self.assertEqual(hashlib.sha256((ROOT/gen.DOC/metadata['path']).read_bytes()).hexdigest(),metadata['sha256'])

    def test_complete_scoped_catalog(self):
        self.assertEqual(len(self.models),244)
        self.assertEqual(int(self.s['catalogue']['pagination']['total']),len(self.models))
        self.assertFalse(self.s['catalogue']['pagination']['hasNext'])
        self.assertEqual(len({m['sku_id'] for m in self.models.values()}),len(self.models))

    def test_partial_or_duplicate_catalog_rejected(self):
        for mutate in ('next','missing','duplicate'):
            s=copy.deepcopy(self.s)
            if mutate=='next':s['catalogue']['pagination']['hasNext']=True
            elif mutate=='missing':s['models'].pop()
            else:s['models'][-1]=s['models'][0]
            with self.subTest(mutate=mutate),self.assertRaises(ValueError):public.validate(s)

    def test_all_explicit_2k_video_tables_present(self):
        target=[m for m in self.models.values() if m['output_type']=='video' and '2k' in [r.lower() for r in m['resolution_options']]]
        self.assertEqual(len(target),26)
        self.assertTrue(all(m['sku_id'] in public.tables(self.s) for m in target))
        self.assertEqual(sum(gen.classification(m)=='direct_text' for m in target),5)

    def test_six_anonymous_calculations_are_not_live_bills(self):
        quotes=self.s['h3_public_calculations'];self.assertEqual(len(quotes),6)
        for q in quotes:
            fields={p['fieldKey']:p['fieldValue'] for p in q['request']['priceFactors']}
            rate=gen.rate(self.models[public.H3],fields['resolution'],self.e)
            self.assertEqual(Decimal(str(q['body']['data']['estimatedPrice'])),Decimal(rate['cny'])*Decimal(fields['duration']))
            self.assertEqual(q['body']['data']['currency'],'CNY')
        self.assertFalse(self.s['authenticated']);self.assertEqual(self.s['paid_task_count'],0)

    def test_exact_h3_family_prices_are_separate_sources(self):
        expectations=[(public.H3,'768P','0.48'),('minimax/hailuo-h3-max/text-to-video','768P','0.63'),('minimax/h3-max-turbo/text-to-video','768p','0.34'),(public.REGEN,'2K','0.3')]
        for ep,res,value in expectations:
            with self.subTest(endpoint=ep):self.assertEqual(gen.rate(self.models[ep],res,self.e)['cny'],value)

    def test_no_implicit_sibling_rate(self):
        e=copy.deepcopy(self.e)
        e['platform_prices']=[p for p in e['platform_prices'] if p['endpoint']==public.H3]
        self.assertIsNone(gen.rate(self.models[public.REGEN],'2K',e)['cny'])

    def test_multimodal_addons_not_flat_total(self):
        m=self.models['minimax/hailuo-h3/multimodal-to-video']
        price=gen.rate(m,'2K',self.e)
        self.assertEqual(price['cny'],'0.77');self.assertFalse(price['exact'])
        self.assertTrue(price['constraints']['condition_rows'])

    def test_token_plus_seconds_never_becomes_flat_rate(self):
        ep='bytedance/seedance-2.5-token/text-to-video'
        self.assertIsNone(gen.rate(self.models[ep],'2k',self.e)['cny'])
        row=next(r for r in gen.cost_rows(self.r,self.e,'2K') if r['endpoint']==ep)
        self.assertEqual(row['full_cost_status'],'incomplete')
        self.assertNotEqual(row['five_second_cost'],'¥2.10')

    def test_generation_regeneration_no_double_source_charge(self):
        self.assertEqual(public.regeneration_budget(5,5,'0.48','0.30'),Decimal('3.90'))
        self.assertEqual(public.regeneration_budget(10,10,'0.48','0.30'),Decimal('7.80'))
        self.assertEqual(public.regeneration_budget(15,15,'0.48','0.30'),Decimal('11.70'))
        self.assertEqual(public.regeneration_budget(5,'5.167','0.48','0.30'),Decimal('3.95010'))

    def test_upscaler_ceiling_and_minimum(self):
        self.assertEqual(public.upscale_budget(5,'5.167','0.48','0.35'),Decimal('4.50'))
        self.assertEqual(public.upscale_budget(5,'5','0.48','0.35'),Decimal('4.15'))
        self.assertEqual(public.upscale_budget(5,'3','0.48','0.35'),Decimal('4.15'))

    def test_nonfinite_or_invalid_seconds_rejected(self):
        for seconds in ('NaN','Infinity','-1','0'):
            with self.subTest(seconds=seconds),self.assertRaises(ValueError):public.upscale_budget(5,seconds,'0.48','0.35')

    def test_stage_quotes_do_not_close_real_billing(self):
        rows=[r for r in gen.cost_rows(self.r,self.e,'2K') if r['route_class'].startswith('two-stage')]
        self.assertEqual(len(rows),2)
        self.assertTrue(all(r['full_cost_status']=='public_stage_formula_not_live_bill' for r in rows))
        self.assertTrue(all('未实扣' in r['five_second_cost'] for r in rows))

    def test_real_billing_gaps_remain_explicit(self):
        gaps={g['id']:g for g in self.e['gaps']}
        self.assertEqual(gaps['current-h3-price']['status'],'closed_public_evidence')
        for name in ('enterprise-live-billing','personal-long-duration','coin-cny-rate','dedicated-rental'):
            self.assertNotEqual(gaps[name]['status'],'closed_public_evidence')

    def test_current_cost_rows_use_current_scope(self):
        rows=[r for r in gen.cost_rows(self.r,self.e,'2K') if r['route_id'].startswith('standard:')]
        self.assertEqual(len(rows),26)
        self.assertIn('arklin/video-super-resolution',{r['endpoint'] for r in rows})

    def test_processing_models_are_not_text_only(self):
        for ep in ('arklin/video-super-resolution','volc-enhance-generative/video','volc-enhance-fast/video'):
            self.assertEqual(gen.classification(self.models[ep]),'upscaler')

    def test_personal_history_not_fabricated_or_requeried(self):
        runs=self.e['reported_runs']
        self.assertEqual(sum(r['route']=='personal-ai-app' for r in runs),3)
        self.assertTrue(all(r['evidence_level']=='reported_live_run_not_requeried' for r in runs))
        self.assertEqual(self.s['authorized_runtime']['private_task_queries'],0)

    def test_all_generated_outputs_are_deterministic(self):
        self.assertEqual(gen.write_outputs(ROOT,gen.outputs(ROOT),check=True),[])

if __name__=='__main__':unittest.main()
