import assert from 'node:assert/strict';
import test from 'node:test';
import { checkUploadFiles, fingerprintFile, lookupFingerprint } from '../src/upload-fingerprints.ts';

const bytes = '# 制度\n必须提交原件。';
const makeFile = (name: string, content = bytes) => new File([content], name);

test('renamed identical files have the same fingerprint; changed bytes differ', async () => {
  const hash = await fingerprintFile(makeFile('原件.md'));
  assert.match(hash, /^[a-f0-9]{64}$/);
  assert.equal(await fingerprintFile(makeFile('改名.md')), hash);
  assert.notEqual(await fingerprintFile(makeFile('原件.md', bytes + '已更新')), hash);
});

test('existing library and repeated selections are skipped while unique files are kept', async () => {
  const original = makeFile('原件.md');
  const hash = await fingerprintFile(original);
  const library = [{ id: 'existing', title: '已有制度', sha256: hash }];
  const result = await checkUploadFiles([
    makeFile('改名.md'), makeFile('新制度.md', '新内容'), makeFile('新制度副本.md', '新内容'),
  ], library, async () => null);
  assert.deepEqual(result.accepted.map(item => item.file.name), ['新制度.md']);
  assert.deepEqual(result.duplicates.map(item => item.file.name), ['改名.md', '新制度副本.md']);
  assert.equal(result.duplicates[0].existing.document_id, 'existing');
  assert.equal(result.duplicates[1].reason, 'batch');
});

test('backend match is skipped even when not loaded in the current page', async () => {
  const existing = { document_id: 'remote', title: '库内旧制度', version_id: 'v1', filename: '旧文件.md', version_no: 1 };
  const result = await checkUploadFiles([makeFile('新名字.md')], [], async () => existing);
  assert.equal(result.accepted.length, 0);
  assert.equal(result.duplicates[0].existing.document_id, 'remote');
});

test('a failed backend check stops the upload rather than treating it as unique', async () => {
  await assert.rejects(checkUploadFiles([makeFile('制度.md')], [], async () => {
    throw new Error('暂时无法检查重复文件');
  }), /无法检查/);
});

test('lookup validates server responses and never accepts non-JSON or inconsistent success', async () => {
  const hash = 'a'.repeat(64);
  for (const body of [{}, { file_sha256: hash, duplicate: false, existing: {} }]) {
    await assert.rejects(lookupFingerprint(hash, undefined, async () => Response.json(body)), /校验/);
  }
  await assert.rejects(lookupFingerprint(hash, undefined, async () => new Response('bad', { status: 503 })), /检查/);
  assert.equal(await lookupFingerprint(hash, undefined, async () => Response.json({
    file_sha256: hash, duplicate: false, existing: null,
  })), null);
});

test('canceled checks cannot produce an import plan', async () => {
  const controller = new AbortController();
  controller.abort();
  await assert.rejects(checkUploadFiles([makeFile('制度.md')], [], async () => null, controller.signal), { name: 'AbortError' });
});
