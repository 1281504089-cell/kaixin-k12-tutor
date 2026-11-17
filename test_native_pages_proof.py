import copy
import json
from pathlib import Path
import unittest
from ci_picture_fresh import NATIVE_PAGE_CHECKS, validate_native_page_views, validate_native_page_api

ROOT=Path(__file__).resolve().parent

class NativeProofTests(unittest.TestCase):
    def setUp(self):
        self.expected=json.loads((ROOT/'attachment-release.json').read_text())['native_pages']
        self.fixture=self.expected['ui_fixture']
        page={'renderer':'native-pages',**{k:self.fixture[k] for k in ['qualified_id','bank_revision']},**{k:self.fixture['native'][k] for k in ['sha256','bytes','page_count','start_page','end_page']},**dict.fromkeys(NATIVE_PAGE_CHECKS,True)}
        self.ui={'passed':True,'actualNativeRenderer':True,'schema_version':2,'bank_revision':self.fixture['bank_revision'],'views':[{'preparedPicture':dict.fromkeys(['native_http_image_sha_verified','body_dom_before_image_response','second_history_restore'],True),'nativePages':copy.deepcopy(page)} for _ in range(4)]}
        self.api={'native_pages':{**{k:self.expected[k] for k in ['manifest_sha256','records','pdfs','total_bytes']},'passed':True,'model_calls':0,'wrong_sha_and_revision_rejected':True,'samples':[{'subject':s,'qualified_id':s,'frozen_payload_and_assets_bound':True,'private_pdf_http_sha_verified':True} for s in ['math','physics','biology','chemistry']]}}

    def test_valid_both_renderers_and_native_api(self):
        validate_native_page_views(self.ui,self.fixture)
        validate_native_page_api(self.api,self.expected)

    def test_every_view_and_each_new_guard_is_required(self):
        for i in range(4):
            for key in NATIVE_PAGE_CHECKS:
                bad=copy.deepcopy(self.ui);bad['views'][i]['nativePages'][key]=False
                with self.subTest(view=i,key=key),self.assertRaises(AssertionError):validate_native_page_views(bad,self.fixture)

    def test_exact_source_sha_bytes_and_pages(self):
        for key,value in [('renderer','html'),('qualified_id','wrong'),('bank_revision','0'*64),('sha256','0'*64),('bytes',0),('page_count',0),('start_page',0),('end_page',999)]:
            bad=copy.deepcopy(self.ui);bad['views'][0]['nativePages'][key]=value
            with self.subTest(key=key),self.assertRaises(AssertionError):validate_native_page_views(bad,self.fixture)

    def test_legacy_image_proof_still_required(self):
        for key in self.ui['views'][0]['preparedPicture']:
            bad=copy.deepcopy(self.ui);bad['views'][0]['preparedPicture'][key]=False
            with self.subTest(key=key),self.assertRaises(AssertionError):validate_native_page_views(bad,self.fixture)

    def test_native_api_manifest_and_all_subjects_required(self):
        for key in ['manifest_sha256','records','pdfs','total_bytes','model_calls','wrong_sha_and_revision_rejected']:
            bad=copy.deepcopy(self.api);bad['native_pages'][key]=None
            with self.subTest(key=key),self.assertRaises(AssertionError):validate_native_page_api(bad,self.expected)
        bad=copy.deepcopy(self.api);bad['native_pages']['samples'][0]['private_pdf_http_sha_verified']=False
        with self.assertRaises(AssertionError):validate_native_page_api(bad,self.expected)

if __name__=='__main__':unittest.main()
