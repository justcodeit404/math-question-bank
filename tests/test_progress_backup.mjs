// 回归：数学题库备份必须包含手写笔记正文、填空答案和笔记图片，
// 且 >80 条笔记走分片存储时不能只导出主 key。
// 运行：node tests/test_progress_backup.mjs（由 tests/test_progress_backup.py 包装进 pytest）
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';

const root = join(dirname(fileURLToPath(import.meta.url)), '..');
const viewerSrc = readFileSync(join(root, '880题', 'math-bank', 'index.html'), 'utf8');

function extractFunction(src, name) {
  const start = src.indexOf('function ' + name + '(');
  if (start < 0) throw new Error('function not found in viewer: ' + name);
  const braceStart = src.indexOf('{', start);
  let depth = 0;
  for (let i = braceStart; i < src.length; i++) {
    if (src[i] === '{') depth++;
    else if (src[i] === '}') {
      depth--;
      if (depth === 0) return src.slice(start, i + 1);
    }
  }
  throw new Error('unbalanced braces: ' + name);
}

// ---- 最小浏览器环境 ----
const store = new Map();
globalThis.window = globalThis;
globalThis.localStorage = {
  getItem: (k) => (store.has(k) ? store.get(k) : null),
  setItem: (k, v) => { store.set(k, String(v)); },
  removeItem: (k) => { store.delete(k); },
  clear: () => { store.clear(); },
};
globalThis.document = { title: '880题' };

const require = createRequire(import.meta.url);
require('../vendor/viewer-common/storage.js');
assert.ok(globalThis.ViewerStorage, 'ViewerStorage loaded from vendored storage.js');

const FN = [
  'getBankProgressKeys',
  'notesKey',
  'noteImgsKey',
  'fillAnswersKey',
  'readShardedMap',
  'mergeShardedMap',
  'getNoteImagesForExport',
  'applyNoteImagesImport',
  'buildProgressData',
  'applyProgressData',
];
const body = FN.map((name) => extractFunction(viewerSrc, name)).join('\n');

const harness = `
let bank = { title: '880题' };
let BANK_KEY = '880';
let MARKS_KEY = 'mathbank_marks_880';
let CURSOR_KEY = 'mathbank_cursor_880';
let PRACTICE_KEY = 'mathbank_practice_880';
let notesMapCache = null;
let noteImgsMapCache = null;
${body}
return { buildProgressData, applyProgressData, notesKey, noteImgsKey, fillAnswersKey, getBankProgressKeys };`;

const api = new Function(harness)();
const VS = globalThis.ViewerStorage;

function writeSharded(key, map) {
  assert.equal(VS.saveShardedMap(key, map), true, 'save ' + key);
}

function makeNotes(count) {
  const notes = {};
  for (let i = 1; i <= count; i++) notes['880-' + i] = '第 ' + i + ' 题的手写笔记';
  notes['880-7'] = '这题注意 ![手写推导](data:image/png;base64,AAAA) 的符号';
  return notes;
}

function resetStorage() {
  VS.clearShardedMap(api.notesKey());
  VS.clearShardedMap(api.noteImgsKey());
  VS.clearShardedMap(api.fillAnswersKey());
  for (const key of Object.values(api.getBankProgressKeys())) VS.clearShardedMap(key);
  store.clear();
}

// ---- 1. 导出 → 清空 → 导入，>80 条笔记 + 图片引用 + 填空答案完整还原 ----
resetStorage();

const notes = makeNotes(120);
writeSharded(api.notesKey(), notes);
assert.ok(localStorage.getItem(api.notesKey() + '__meta'), '120 条笔记应写成分片');

const fill = { '880-81': 'x=1', '880-93': 'A^{-1}B', '880-165': '\\frac{1}{2}' };
writeSharded(api.fillAnswersKey(), fill);

const noteImages = { '880-7': 'data:image/png;base64,AAAA' };
writeSharded(api.noteImgsKey(), noteImages);

writeSharded(api.getBankProgressKeys().marks, { '880-1': 2, '880-2': 1 });
localStorage.setItem(api.getBankProgressKeys().theme, JSON.stringify('dark'));
localStorage.setItem(api.getBankProgressKeys().last, JSON.stringify('880-120'));

const backup = api.buildProgressData();
assert.equal(backup.version, 3, '备份版本应为 3');
assert.equal(Object.keys(backup.notes).length, 120, '分片笔记必须整份导出');
assert.equal(backup.notes['880-120'], '第 120 题的手写笔记');
assert.ok(backup.notes['880-7'].includes('data:image/png;base64,AAAA'), '笔记里的图片引用要保留');
assert.deepEqual(backup.fill, fill, '填空答案必须导出');
assert.deepEqual(backup.noteImages, noteImages, '笔记图片必须导出');
assert.deepEqual(backup.marks, { '880-1': 2, '880-2': 1 }, '掌握度必须导出');
assert.equal(backup.theme, 'dark');

const serialized = JSON.parse(JSON.stringify(backup));
resetStorage();
assert.deepEqual(VS.loadShardedMap(api.notesKey()), {}, '清空后本地应无笔记');

api.applyProgressData(serialized);

const restoredNotes = VS.loadShardedMap(api.notesKey());
assert.equal(Object.keys(restoredNotes).length, 120, '导入后笔记数量应完整');
assert.equal(restoredNotes['880-120'], '第 120 题的手写笔记');
assert.ok(restoredNotes['880-7'].includes('data:image/png;base64,AAAA'), '笔记图片引用应在导入后保留');
assert.deepEqual(VS.loadShardedMap(api.fillAnswersKey()), fill, '填空答案应完整还原');
assert.deepEqual(VS.loadShardedMap(api.noteImgsKey()), noteImages, '笔记图片应完整还原');
assert.deepEqual(VS.loadShardedMap(api.getBankProgressKeys().marks), { '880-1': 2, '880-2': 1 });

// ---- 2. 旧备份（version 2，没有 notes/fill）不能清空现有数据 ----
resetStorage();
writeSharded(api.notesKey(), { '880-1': '现有笔记' });
writeSharded(api.fillAnswersKey(), { '880-1': '现有填空' });

api.applyProgressData({ version: 2, bank: '880题', marks: { '880-3': 2 } });

assert.deepEqual(VS.loadShardedMap(api.notesKey()), { '880-1': '现有笔记' }, '旧备份不得清空笔记');
assert.deepEqual(VS.loadShardedMap(api.fillAnswersKey()), { '880-1': '现有填空' }, '旧备份不得清空填空答案');
assert.deepEqual(VS.loadShardedMap(api.getBankProgressKeys().marks), { '880-3': 2 }, 'mark 仍按备份还原');

// ---- 3. 非法备份报错而不是静默成功 ----
assert.throws(() => api.applyProgressData(null), /无效文件/);

resetStorage();
console.log('test_progress_backup: ok');
