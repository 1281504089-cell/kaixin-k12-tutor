import io,json,os,subprocess,tarfile,tempfile
from pathlib import Path
binary=Path(os.environ['SystemRoot'])/'System32/tar.exe'
print(subprocess.check_output([str(binary),'--version'],text=True))
results=[]
with tempfile.TemporaryDirectory(prefix='KX archive probe ') as folder:
    root=Path(folder);source=root/'input';(source/'资料').mkdir(parents=True)
    (source/'ascii.txt').write_text('safe',encoding='utf-8');(source/'资料/公式α.txt').write_text('负二分之一',encoding='utf-8')
    for name,fmt in [('pax',tarfile.PAX_FORMAT),('gnu',tarfile.GNU_FORMAT),('ustar',tarfile.USTAR_FORMAT)]:
        memory=io.BytesIO()
        with tarfile.open(fileobj=memory,mode='w:gz',format=fmt) as archive:archive.add(source,arcname='.')
        data=memory.getvalue()
        for label,extra in [('default',{}),('dotUTF8',{'LC_ALL':'.UTF8','LANG':'.UTF8'}),('enUS',{'LC_ALL':'en_US.UTF-8','LANG':'en_US.UTF-8'}),('CUTF8',{'LC_ALL':'C.UTF-8','LANG':'C.UTF-8'})]:
            for options in [[],['--options','hdrcharset=UTF-8']]:
                output=root/f'测试 {len(results)}';output.mkdir();r=subprocess.run([str(binary),'-xzf','-',*options],input=data,cwd=output,env={**os.environ,**extra},capture_output=True)
                expected=output/'资料/公式α.txt'
                results.append({'format':name,'locale':label,'options':options,'exit':r.returncode,'correct':expected.exists() and expected.read_text(encoding='utf-8')=='负二分之一','stderr':r.stderr.decode(errors='replace')[:180]})
    memory=io.BytesIO()
    with tarfile.open(fileobj=memory,mode='w:gz',format=tarfile.PAX_FORMAT) as archive:
        relative='student-seed/reading/'+'9'*64+'/raw/source.pdf';info=tarfile.TarInfo(relative); payload=b'verified sample';info.size=len(payload);archive.addfile(info,io.BytesIO(payload))
    output=root/'全新 学生资料';output.mkdir();r=subprocess.run([str(binary),'-xzf','-'],input=memory.getvalue(),cwd=output,capture_output=True)
    file=output/relative;results.append({'format':'pax-ascii','locale':'default','options':[],'exit':r.returncode,'correct':file.exists() and file.read_bytes()==payload,'stderr':r.stderr.decode(errors='replace')[:180]})
print('ARCHIVE_PROBE='+json.dumps(results,ensure_ascii=False))
