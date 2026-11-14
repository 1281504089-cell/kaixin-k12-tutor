import test from 'node:test';
import assert from 'node:assert/strict';
import { execFileSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';

test('runtime archive preserves Unicode names and rejects archiving inside itself', () => {
  const script = fileURLToPath(new URL('../scripts/archive-runtime.py', import.meta.url));
  const python = process.env.STUDENT_TEST_PYTHON ?? (process.platform === 'win32' ? 'python' : 'python3');
  const check = `import pathlib,subprocess,sys,tarfile,tempfile
with tempfile.TemporaryDirectory(prefix='KX archive ') as folder:
    root=pathlib.Path(folder); source=root/'input'; source.mkdir()
    (source/'公式 α.txt').write_text('负二分之一',encoding='utf-8')
    out=root/'runtime.tar.gz'
    subprocess.run([sys.executable,sys.argv[1],str(source),str(out)],check=True)
    with tarfile.open(out) as archive:
        assert archive.extractfile('./公式 α.txt').read().decode('utf-8')=='负二分之一'
    result=subprocess.run([sys.executable,sys.argv[1],str(source),str(source/'bad.tar.gz')],capture_output=True)
    assert result.returncode!=0 and not (source/'bad.tar.gz').exists()
`;
  assert.doesNotThrow(() => execFileSync(python, ['-c', check, script], { stdio: 'pipe' }));
});
