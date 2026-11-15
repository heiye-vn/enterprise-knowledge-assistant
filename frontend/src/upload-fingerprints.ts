export type ExistingDocument = {
  document_id: string;
  title: string;
  version_id?: string;
  filename?: string;
  version_no?: number;
};
export type FingerprintedFile = { file: File; sha256: string };
export type DuplicateFile = FingerprintedFile & {
  existing: ExistingDocument;
  reason: 'library' | 'batch';
};
export type UploadCheck = { accepted: FingerprintedFile[]; duplicates: DuplicateFile[] };
type LibraryDocument = { id: string; title: string; sha256?: string };
type Lookup = (hash: string, signal?: AbortSignal) => Promise<ExistingDocument | null>;
type Fetcher = (url: string, init?: RequestInit) => Promise<Response>;

export async function fingerprintFile(file: File): Promise<string> {
  const digest = await crypto.subtle.digest('SHA-256', await file.arrayBuffer());
  return Array.from(new Uint8Array(digest), byte => byte.toString(16).padStart(2, '0')).join('');
}

export async function lookupFingerprint(hash: string, signal?: AbortSignal, request: Fetcher = fetch): Promise<ExistingDocument | null> {
  const response = await request('/api/documents/check-duplicate', {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ file_sha256: hash }), signal,
  });
  if (!response.ok) throw new Error('暂时无法检查重复文件，请稍后重试。');
  let data;
  try { data = await response.json(); }
  catch { throw new Error('重复检查结果校验失败，请稍后重试。'); }
  if (!data || data.file_sha256 !== hash || typeof data.duplicate !== 'boolean') {
    throw new Error('重复检查结果校验失败，请稍后重试。');
  }
  if (!data.duplicate && data.existing === null) return null;
  const existing = data.existing;
  if (data.duplicate && existing && typeof existing.document_id === 'string' && existing.document_id &&
      typeof existing.title === 'string' && existing.title && typeof existing.filename === 'string' &&
      typeof existing.version_id === 'string' && Number.isInteger(existing.version_no) && existing.version_no > 0) {
    return existing;
  }
  throw new Error('重复检查结果校验失败，请稍后重试。');
}

export async function checkUploadFiles(files: File[], library: LibraryDocument[], lookup: Lookup = lookupFingerprint, signal?: AbortSignal): Promise<UploadCheck> {
  const result: UploadCheck = { accepted: [], duplicates: [] };
  const known = new Map<string, { existing: ExistingDocument; reason: 'library' | 'batch' }>();
  for (const doc of library) {
    if (doc.sha256) known.set(doc.sha256, { existing: { document_id: doc.id, title: doc.title }, reason: 'library' });
  }
  for (const file of files) {
    signal?.throwIfAborted();
    const sha256 = await fingerprintFile(file);
    signal?.throwIfAborted();
    let match = known.get(sha256);
    if (!match) {
      const existing = await lookup(sha256, signal);
      signal?.throwIfAborted();
      if (existing) match = { existing, reason: 'library' };
    }
    if (match) {
      result.duplicates.push({ file, sha256, ...match });
      known.set(sha256, match);
    } else {
      result.accepted.push({ file, sha256 });
      known.set(sha256, { existing: { document_id: '', title: file.name }, reason: 'batch' });
    }
  }
  return result;
}
