import test from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { MESSAGES, resolveLanguage, translate } from '../src/i18n.mjs';

test('a fresh student install starts in Chinese and preserves an explicit language choice', () => {
  assert.equal(resolveLanguage(undefined), 'zh');
  assert.equal(resolveLanguage('auto'), 'zh');
  assert.equal(resolveLanguage('en'), 'en');
  assert.equal(translate(undefined, 'firstLaunch'), '首次打开：正在准备内置运行环境');
  assert.equal(resolveLanguage('zh'), 'zh');
  assert.equal(resolveLanguage('zh-CN'), 'zh');
  assert.equal(translate('fr', 'retry'), 'Réessayer');
});

test('the initial launcher markup is Chinese before settings are loaded', async () => {
  const html = await readFile(new URL('../src/index.html', import.meta.url), 'utf8');
  assert.match(html, /<html lang="zh"/);
  assert.match(html, /你的个人学习空间/);
});

test('every language translates every shell string', () => {
  const keys = Object.keys(MESSAGES.en).sort();
  for (const [language, messages] of Object.entries(MESSAGES)) {
    assert.deepEqual(Object.keys(messages).sort(), keys, language);
  }
});

test('every shell language uses the student product name', () => {
  for (const [language, messages] of Object.entries(MESSAGES)) {
    for (const [key, message] of Object.entries(messages)) {
      assert.doesNotMatch(message, /DeepTutor|Dito/, `${language}:${key}`);
    }
    assert.match(translate(language, 'startingCore'), /开心动力超级学霸/);
  }
});

test('placeholders are filled and unknown ones are left visible', () => {
  assert.match(translate('en', 'workerExited', { code: 3 }), /\(3\)/);
  assert.match(translate('de', 'aboutDetail', { core: '1.7.0' }), /Kern 1\.7\.0\nBuild \{runtime\}/);
});


test('Portuguese shell follows the selected locale and retains formatted values', () => {
  assert.equal(resolveLanguage('pt-BR'), 'pt');
  assert.equal(translate('pt', 'retry'), 'Tentar novamente');
  assert.match(translate('pt', 'workerExited', { code: 3 }), /\(3\)/);
  for (const [key, value] of Object.entries(MESSAGES.en)) {
    const placeholders = (text) => [...text.matchAll(/\{[^}]+\}/g)].map(([token]) => token).sort();
    assert.deepEqual(placeholders(MESSAGES.pt[key]), placeholders(value), key);
  }
});

test('Turkish shell follows regional interface codes and formats runtime details', () => {
  assert.equal(resolveLanguage('tr-TR'), 'tr');
  assert.equal(resolveLanguage('tr_TR'), 'tr');
  assert.equal(translate('tr', 'retry'), 'Yeniden dene');
  assert.match(translate('tr', 'workerExited', { code: 3 }), /3/);
});
