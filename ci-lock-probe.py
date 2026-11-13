"""Run the exact queue function with native Windows byte-range locks, no AI dependencies."""
import ast,asyncio,errno,json,os,tempfile
from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace

with tempfile.TemporaryDirectory() as temporary:
 root=Path(temporary)
 module=ast.parse(Path('queue-probe-source.py').read_text(encoding='utf-8'))
 definition=next(n for n in module.body if isinstance(n,ast.AsyncFunctionDef) and n.name=='library_queue')
 scope={'asynccontextmanager':asynccontextmanager,'asyncio':asyncio,'os':os,'errno':errno,'store':lambda:SimpleNamespace(root=root)}
 exec(compile(ast.Module(body=[definition],type_ignores=[]),'queue-probe-source.py','exec'),scope)
 queue=scope['library_queue']
 async def run():
  order=[];release=asyncio.Event()
  async def first():
   async with queue():order.append('first');await release.wait()
  async def second():
   async with queue():order.append('second')
  a=asyncio.create_task(first());await asyncio.sleep(.03)
  b=asyncio.create_task(second());await asyncio.sleep(.08);assert order==['first'],order
  release.set();await asyncio.wait_for(asyncio.gather(a,b),5);assert order==['first','second']
  try:
   async with queue():raise ValueError('Synthetic cancellation')
  except ValueError:pass
  async with queue():pass
  assert (root/'.library-upload.lock').stat().st_size==0
  return {'platform':os.name,'empty_lock_supported':True,'concurrent_queue_order':order,'exception_unlock':True}
 result=asyncio.run(run());Path('lease-probe.json').write_text(json.dumps(result,indent=2));print(json.dumps(result))
