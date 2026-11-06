import { execFileSync } from 'node:child_process';
import { readFile, mkdir, writeFile } from 'node:fs/promises';
import path from 'node:path';
import { createRequire } from 'node:module';
import assert from 'node:assert/strict';
import { pathToFileURL } from 'node:url';

const root = process.cwd();
const desktop = path.join(root, 'apps/desktop');
const { loadTarget } = await import(pathToFileURL(path.join(desktop, 'scripts/lib/target.mjs')));
const { studentEnvironment } = await import(pathToFileURL(path.join(desktop, 'src/student-runtime.mjs')));
const { bundleConfig } = await import(pathToFileURL(path.join(desktop, 'src/bundles.mjs')));
const target = await loadTarget();
const manifest = JSON.parse(await readFile(path.join(target.seed, 'runtime.json')));
const home = path.join(target.local, 'component-home');
const output = path.join(target.local, 'native-evidence');
await mkdir(output, { recursive: true });
const config = bundleConfig(target.runtime, home, manifest.runtimeId);
const require = createRequire(path.join(desktop, 'package.json'));
const env = { ...process.env, ...studentEnvironment(config, path.join(target.local, 'component-cache')),
  PYTHONPATH: path.join(target.runtime, 'core'), DEEPTUTOR_HOME: home,
  DEEPTUTOR_ELECTRON_EXECUTABLE: require('electron'),
  DEEPTUTOR_ELECTRON_PROBE: path.join(desktop, 'src/lesson-browser.cjs') };
for (const extra of [[], ['--local-ai-only']]) {
  execFileSync(config.pythonPath, [path.join(target.runtime, 'core/scripts/verify-student-runtime.py'),
    '--output', output, ...extra], { cwd: config.sourcePath, env, stdio: 'inherit' });
}
const components = JSON.parse(await readFile(path.join(output, 'components.json')));
assert.equal(components.remotion_browser_layout.ok, true, 'Native Electron layout probe must run');
await writeFile(path.join(output, 'native-build.json'), JSON.stringify({ target: target.id,
  sourceCommit: manifest.commit, approvedSource: JSON.parse(await readFile(path.join(root, 'SOURCE_FREEZE.json'))).commit,
  nativeComponents: 'passed', privateKeysUploaded: false, textbooks: 'merge locally before delivery' }, null, 2));
