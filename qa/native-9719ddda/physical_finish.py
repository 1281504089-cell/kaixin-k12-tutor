"""Bind the physical Intel Mac's signature and student results to this native runner's exact media."""
from base64 import b64decode
from hashlib import sha256
import json,os,re,subprocess,sys,time
from pathlib import Path
from urllib.request import Request,urlopen
from urllib.error import HTTPError,URLError

here=Path(__file__).resolve().parent
e=Path(sys.argv[1])
stage=json.loads((e/'physical-intel-pending.json').read_bytes())
run=os.environ['GITHUB_RUN_ID']
assert not stage['passed'] and stage['pending']==['physical_student_window'] and stage['run_id']==run
assert stage['target']=='macos-x64' and stage['runner']=='x86_64' and stage['workflow_sha']==os.environ['GITHUB_SHA']
repo='1281504089-cell/kaixin-k12-tutor'
def get(url,limit):
    with urlopen(Request(url,headers={'User-Agent':'Scholar exact-media native verification','Cache-Control':'no-cache'}),timeout=20) as response:
        data=response.read(limit+1)
    assert len(data)<=limit
    return data

branch='codex/desktop-native-qa-5af77432'
prefix=f'qa/physical-intel-9719ddda/{run}'
end=time.monotonic()+170*60
while True:
    try:
        ref=json.loads(get(f'https://api.github.com/repos/{repo}/git/ref/heads/{branch}',12000))['object']['sha']
        assert re.fullmatch('[a-f0-9]{40}',ref)
        base=f'https://raw.githubusercontent.com/{repo}/{ref}/{prefix}'
        document=get(base+'.json',160000)
        signature=get(base+'.json.sig',8000)
        break
    except (HTTPError,URLError,TimeoutError) as error:
        if time.monotonic()>end:raise TimeoutError('Physical Intel proof is still pending') from error
        time.sleep(60)
sig=e/'physical-intel.signature';sig.write_bytes(signature)
subprocess.run(['ssh-keygen','-Y','verify','-f',str(here/'physical-signers'),'-I','release-owner',
                '-n','scholar-native-acceptance','-s',str(sig)],input=document,check=True)
p=json.loads(document)
for key in ('source_commit','core','target','run_id','workflow_sha','installer_media'):
    assert stage[key]==p[key],key
assert p['on_device'] is True and p['signed_app_verified'] and p['volume_checksums_verified']
assert p['processor']=='x86_64' and p['native_gpu'] and p['active_commit']==p['source_commit']
assert len(p['installer_media'])==5 and not p['real_learning_data_used']
features=p['student_features']
assert features['commit']==p['source_commit'] and features['target']==p['target']
assert '正确' in features['attached_exercise']['feedback']
assert not features['offline_experiment']['errors'] and not features['offline_experiment']['sceneErrors']
assert features['offline_experiment']['workbench']['released']
assert features['offline_dictation_with_synthetic_audio']['format']['sampleRate']==16000
assert all(features['illustrated_exercises'][m]['submitted'] and features['illustrated_exercises'][m]['count']==n for m,n in [('quiz',3),('always',2)])
def write(name,value):
    (e/name).write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
write('physical-on-device.json',p)
write('student-features.json',features)
stage.pop('pending');stage.update(passed=True,student_features=features,physical_proof={'sha256':sha256(document).hexdigest(),
    'proof_commit':ref,'native_installer_checks':'hosted Intel Mac','student_window':'physical Intel Mac using exact same installation volumes'})
write('native-acceptance.json',stage)
print('Verified physical Intel student window and the five native-tested volumes.')
