"""Exercise real original upload, native OCR and local indexing in an empty profile."""
import asyncio,concurrent.futures,hashlib,json,os,sys,tempfile,time
from pathlib import Path
import httpx,pymupdf
BASE=sys.argv[1];OUT=Path(sys.argv[2]);client=httpx.Client(base_url=BASE,timeout=45)
def upload(file,retention):
 start=time.monotonic();r=client.post('/api/student/attachments/uploads',json={'filename':file.name,'size':file.stat().st_size,'retention':retention});r.raise_for_status();meta=r.json()
 with file.open('rb') as stream:
  i=0
  while chunk:=stream.read(meta['chunk_bytes']):
   r=client.put(f"/api/student/attachments/uploads/{meta['upload_id']}/chunks/{i}",content=chunk,headers={'X-Upload-SHA256':hashlib.sha256(chunk).hexdigest()});r.raise_for_status();i+=1
 r=client.post(f"/api/student/attachments/uploads/{meta['upload_id']}/complete");r.raise_for_status();row=r.json()
 assert client.get(row['records'][0]['url']).content==file.read_bytes()
 return row,round(time.monotonic()-start,3)
async def retrieve():
 from deeptutor.services.rag import RAGService
 result=await RAGService().search('分数相加怎样通分',kb_name='我的上传资料',rewrite=False)
 sources=result.get('sources',[])
 assert any('原件扫描.pdf' in s.get('title','') and '通分' in s.get('content','') for s in sources),result
 return len(sources)
with tempfile.TemporaryDirectory(prefix='附件验收-') as temp:
 root=Path(temp);text=root/'长期分数.txt';text.write_text('分数相加先通分：二分之一加三分之一等于六分之五。',encoding='utf-8')
 with pymupdf.open() as source:
  p=source.new_page(width=1000,height=300);p.insert_font(fontname='cn',fontfile=str(Path(os.environ['DEEPTUTOR_FONT_DIR'])/'NotoSansCJKsc-Regular.otf'));p.insert_text((30,100),'分数相加先通分。二分之一加三分之一等于六分之五。',fontsize=28,fontname='cn')
  pixels=p.get_pixmap(matrix=pymupdf.Matrix(1.5,1.5))
  with pymupdf.open() as scan:
   scan.new_page(width=1000,height=300).insert_image(pymupdf.Rect(0,0,1000,300),pixmap=pixels);scan.save(root/'原件扫描.pdf')
 with pymupdf.open() as short:
  short.new_page().insert_text((40,80),'1/2 + 1/3 = 5/6');short.new_page().insert_text((40,80),'x^2+y^2=25');short.save(root/'临时两页.pdf')
 temporary,seconds=upload(root/'临时两页.pdf','temporary');assert temporary['records'][0]['page_count']==2
 with concurrent.futures.ThreadPoolExecutor(2) as pool:
  futures=[pool.submit(upload,f,'library') for f in [text,root/'原件扫描.pdf']]
  uploaded=[f.result() for f in futures]
 started=time.monotonic()
 with (root/'临时两页.pdf').open('rb') as stream:
  ready=client.post('/api/student/attachments/prepare',files={'file':('当前页.pdf',stream,'application/pdf')})
 ready.raise_for_status();assert ready.json()['strategy']=='vision'
 interactive_seconds=time.monotonic()-started
 assert interactive_seconds<20,interactive_seconds
 samples=[];start=time.monotonic()
 while time.monotonic()-start<300:
  at=time.monotonic();response=client.get('/health/ready');response.raise_for_status();samples.append(time.monotonic()-at)
  listing=client.get('/api/student/attachments/uploads/library');listing.raise_for_status();rows=listing.json()['uploads']
  assert not any(r['upload_id']==temporary['upload_id'] for r in rows)
  retained=[next(r for r in rows if r['upload_id']==u[0]['upload_id']) for u in uploaded]
  assert not any(r['library_status']=='failed' for r in retained),retained
  if all(r['library_status']=='saved' for r in retained):break
  time.sleep(.3)
 else:raise AssertionError('Native indexing never completed')
 count=asyncio.run(retrieve())
 report={'raw_originals_verified':True,'temporary_excluded_from_library':True,'short_pdf_pages':2,'concurrent_library_uploads_saved':True,'scanned_pdf_retrievable':True,'sources':count,'interactive_page_ready_while_indexing_seconds':round(interactive_seconds,3),'temporary_raw_seconds':seconds,'library_raw_seconds':[r[1] for r in uploaded],'background_and_retrieval_seconds':round(time.monotonic()-start,3),'health_max_seconds':round(max(samples),3),'real_api_key_used':False,'cloud_models_used':False}
 assert max(samples)<5,report
 OUT.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8');print(json.dumps(report,ensure_ascii=False))
