"""Stop only this owner's superseded, unqualified native candidate."""
import json,os,subprocess

repo=os.environ['GH_REPO'];assert repo=='1281504089-cell/kaixin-k12-tutor'
run=json.loads(subprocess.check_output(['gh','api',f'repos/{repo}/actions/runs/44034406403']))
assert run['head_sha']=='be5e026002f9a63c88814202800d96244bec3998'
assert run['head_branch']=='codex/k12-native-20261117-3'
if run['status']!='completed':
 subprocess.run(['gh','api','--method','POST',f'repos/{repo}/actions/runs/44034406403/cancel'],check=True)
release=json.loads(subprocess.check_output(['gh','api',f'repos/{repo}/releases/tags/student-20261117-k12-3']))
assert release['id']==448244228 and release['prerelease'] and not release['draft']
subprocess.run(['gh','release','edit','student-20261117-k12-3','--title','未通过完整验收 · 20261117-k12-3','--notes','此候选保留用于核查。Apple 芯片新增网络验收遇到 GitHub HTTP 403，未晋升稳定版；由后续候选补齐断流与备用通道拒绝的恢复处理。正式版本以 Latest 为准。'],check=True)
print('Superseded candidate stopped; evidence retained; stable release unchanged.')
