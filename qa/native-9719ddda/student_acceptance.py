"""Check normal student controls on the exact native installer using synthetic data."""
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import time
from urllib.request import urlopen

HERE=Path(__file__).resolve().parent
def port():
    with socket.socket() as sock:
        sock.bind(('127.0.0.1',0));return sock.getsockname()[1]

def verify_student(app,home,selected,output,target):
    from ci_repackage import write
    from run_native import stop
    os_name=target=='windows-x64'
    native=home/'runtimes'/selected['baseRuntimeId']
    core=home/'runtimes'/selected['runtimeId']/'core'
    py=native/('python/python.exe' if os_name else 'python/bin/python3')
    cdp,gate=port(),port()
    assert cdp!=gate and py.is_file() and (core/'deeptutor').is_dir()
    env={**os.environ,'DEEPTUTOR_HOME':str(home/'workspace'),'OPEN_DEEPTUTOR_TEST_HOME':str(home),'PYTHONPATH':str(core),'PYTHONDONTWRITEBYTECODE':'1','QA_CDP':str(cdp),'QA_PORT':str(gate),'NEXT_PUBLIC_DEEPTUTOR_LIVEBOOK_PILOT':'1','LIVEBOOK_NATIVE_ONLY':'workbench'}
    for key in ('GH_TOKEN','GITHUB_TOKEN'):env.pop(key,None)
    subprocess.run([py,HERE/'seed_models.py'],env=env,cwd=core,check=True,timeout=90)
    with (output/'student-window.log').open('wb') as log:
        proc=subprocess.Popen([sys.executable,'-u',HERE/'replay.py',str(gate),'candidate'],env=env,cwd=HERE,stdout=log,stderr=log)
        shell=None
        try:
            (HERE/'grade-selected.txt').unlink(missing_ok=True)
            # Hosted Intel runners have no graphics device. Use the application's bundled renderer for this synthetic session.
            graphics=['--use-gl=angle','--use-angle=swiftshader','--enable-unsafe-swiftshader'] if os.getenv('QA_SOFTWARE_GRAPHICS')=='1' else []
            shell=subprocess.Popen([app,'--remote-debugging-port='+str(cdp),'--autoplay-policy=no-user-gesture-required',*graphics],env=env,cwd=app.parent,stdout=log,stderr=log,start_new_session=not os_name)
            for _ in range(360):
                if shell.poll() is not None or proc.poll() is not None:raise RuntimeError('The normal app or fixture quit during student acceptance')
                try:
                    with urlopen(f'http://127.0.0.1:{cdp}/json/list',timeout=1) as response:
                        if any(t.get('url','').startswith('http://127.0.0.1:') for t in json.load(response)):break
                except OSError:pass
                time.sleep(.5)
            else:raise TimeoutError('Normal student app did not show its page')
            for name,args in [('practice',[str(cdp),'candidate','found']),('workbench',[str(cdp)]),('dictation',[])]:
                subprocess.run(['node',HERE/(name+'.cjs'),*args],cwd=output,env=env,check=True,timeout=360)
            proc.terminate()
            proc.wait(timeout=15)
            (HERE/'case').write_text('startup')
            proc=subprocess.Popen([sys.executable,'-u',HERE/'quiz_replay.py'],cwd=HERE,env=env,stdout=log,stderr=log)
            for _ in range(100):
                if proc.poll() is not None:raise RuntimeError('The exercise replay service exited')
                try:
                    with socket.create_connection(('127.0.0.1', gate),timeout=.5):break
                except OSError:time.sleep(.1)
            else:raise TimeoutError('The exercise replay service did not listen')
            batches={}
            for mode,count in [('quiz',3),('always',2)]:
                subprocess.run(['node',HERE/'quiz.cjs',target],cwd=output,env={**env,'QA_CASE_ID':mode,'QA_TRIAL':mode},check=True,timeout=175)
                batch=json.loads((HERE/(mode+target+'-quiz.json')).read_bytes())
                write(output/(mode+'-window.json'),batch)
                assert batch.get('studentTurnVisible') and batch['submitted'] and len(batch['cards'])==count,(mode,batch.get('error'),len(batch['cards']),batch.get('final','')[-500:])
                if mode=='always':
                    assert '2' in batch['final'] and '暂缺' in batch['final'],batch['final']
                batches[mode]={'count':count,'submitted':True,'first_visible_ms':batch['cards'][0]['ms']}
            quiz=json.loads((HERE/'results/found.json').read_bytes())
            voice=json.loads((HERE/'录音与逐题配图.桌面语音回执.json').read_bytes())
            scene=json.loads((output/'native-workbench.json').read_bytes())
            assert quiz['card'] and '课堂练习.txt' in quiz['cardText'] and '正确' in quiz['feedback']
            assert scene['workbench']['operationVisible'] and not scene['errors']
            assert voice['format']['sampleRate']==16000 and '旋转' in voice['offlineTranscript']
            assert json.loads((home/'active.json').read_bytes())['commit']==selected['commit']
            report={'commit':selected['commit'],'target':target,'attached_exercise':quiz,'illustrated_exercises':batches,'offline_experiment':scene,'offline_dictation_with_synthetic_audio':voice}
            write(output/'student-features.json',report)
            return report
        finally:
            if shell is not None:stop(shell)
            proc.terminate();proc.wait(timeout=15)
