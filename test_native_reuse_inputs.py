import copy
import json
from pathlib import Path
import unittest
from ci_repackage import validate_reuse_lock

class ReuseInputTests(unittest.TestCase):
    def setUp(self):
        self.batch=json.loads(Path('attachment-batch.json').read_text())
        target='windows-x64';names=['Kaixin-Super-Scholar-Windows-v1.7.1-'+n for n in ['Setup.exe','Runtime.001','Runtime.002','Runtime.003','Runtime.004']]
        rows=[{'name':n,'id':i+1,'bytes':100,'sha256':'a'*64,'url':'https://github.com/1281504089-cell/kaixin-k12-tutor/releases/download/student-20261117-k12-5/'+n} for i,n in enumerate(names)]
        prior={'commit':'2af326481943f7e072036637ba186aa829dce39d','baseRuntimeId':self.batch['manifests'][target]['baseRuntimeId'],'sha256':'3220d81db122a1805eaa88b3f51de4bd31468192e056ea0bf461079120e9552f','archive':'kaixin-core-20261117-k12-4.tar.gz'}
        self.lock={'tag':'student-20261117-k12-5','release_id':448792391,'core_commit':self.batch['core_commit'],'core_sha256':self.batch['core_asset']['digest'][7:],'targets':{target:{'files':rows}},'reuse_existing_native':{'baseline_latest_id':448283800,'original_native_run':44114676923,'original_native_workflow_commit':'800eeeece85fd1f36a5d3f55854bfabd6baa89dd','original_installer_assets':{target:rows},'prior_manifests':{target:prior},'prior_core_asset':{'sha256':'3220d81db122a1805eaa88b3f51de4bd31468192e056ea0bf461079120e9552f','name':'kaixin-core-20261117-k12-4.tar.gz','bytes':572023510,'id':758074993,'url':'https://github.com/1281504089-cell/kaixin-k12-tutor/releases/download/student-20261117-k12-4/kaixin-core-20261117-k12-4.tar.gz'}}}
        self.release={'tag_name':'student-20261117-k12-5','id':448792391,'prerelease':True,'draft':False,'assets':[{'name':r['name'],'id':r['id'],'size':r['bytes'],'digest':'sha256:'+r['sha256']} for r in rows]}
    def test_exact_original_bytes_accepted_without_network(self):
        validate_reuse_lock(self.lock,self.batch,self.release,'windows-x64')
    def test_changed_asset_id_sha_size_or_publication_state_rejected(self):
        for key,value in [('id',999),('size',999),('digest','sha256:'+'0'*64)]:
            release=copy.deepcopy(self.release);release['assets'][0][key]=value
            with self.subTest(key=key),self.assertRaises(AssertionError):validate_reuse_lock(self.lock,self.batch,release,'windows-x64')
        for key,value in [('id',999),('prerelease',False),('draft',True)]:
            release=copy.deepcopy(self.release);release[key]=value
            with self.subTest(key=key),self.assertRaises(AssertionError):validate_reuse_lock(self.lock,self.batch,release,'windows-x64')
    def test_existing_bridge_or_stage_or_verification_not_overwritten(self):
        for name in ['kaixin-bridge-20261117-k12-5-windows-x64.tar.gz','attachment-stage-windows-x64.json','verification-windows-x64.json']:
            release=copy.deepcopy(self.release);release['assets'].append({'name':name})
            with self.subTest(name=name),self.assertRaises(AssertionError):validate_reuse_lock(self.lock,self.batch,release,'windows-x64')
    def test_mixed_prior_core_or_original_run_rejected(self):
        for key,value in [('baseline_latest_id',0),('original_native_run',0),('original_native_workflow_commit','0'*40)]:
            lock=copy.deepcopy(self.lock);lock['reuse_existing_native'][key]=value
            with self.subTest(key=key),self.assertRaises(AssertionError):validate_reuse_lock(lock,self.batch,self.release,'windows-x64')
        lock=copy.deepcopy(self.lock);lock['reuse_existing_native']['prior_manifests']['windows-x64']['sha256']='0'*64
        with self.assertRaises(AssertionError):validate_reuse_lock(lock,self.batch,self.release,'windows-x64')

if __name__=='__main__':unittest.main()
