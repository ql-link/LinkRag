import { ApiError, request, setToken, setUnauthorizedHandler, withQuery } from '@/api/http';
import { parseSseFrames } from '@/api/stream';
import { displayTime, toDataset, toFile, toModelState } from '@/services/backend';
import { blocksFromAnswer, toChunks } from '@/services/chatRemote';

const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } });

afterEach(() => {
  vi.unstubAllGlobals();
  localStorage.clear();
  setUnauthorizedHandler(undefined);
});

describe('http request', () => {
  it('sends satoken and unwraps {code:200,data}', async () => {
    setToken({ accessToken: 'jwt-1', expiresIn: 7200, userId: 7 });
    const fetchMock = vi.fn().mockResolvedValue(json({ code: 200, message: 'success', data: { id: 1 } }));
    vi.stubGlobal('fetch', fetchMock);
    await expect(request('/api/v1/user/profile')).resolves.toEqual({ id: 1 });
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe('/api/v1/user/profile');
    expect(init.headers).toMatchObject({ satoken: 'jwt-1' });
  });

  it('uses Bearer for RAG routes and JSON-encodes bodies', async () => {
    setToken({ accessToken: 'jwt-2', expiresIn: 7200, userId: 7 });
    const fetchMock = vi.fn().mockResolvedValue(json({ code: 'OK', data: { stopped: true } }));
    vi.stubGlobal('fetch', fetchMock);
    await expect(request('/api/v1/rag/stream/t1/cancel', { method: 'POST', bearer: true })).resolves.toEqual({ stopped: true });
    expect(fetchMock.mock.calls[0][1].headers).toMatchObject({ Authorization: 'Bearer jwt-2' });
  });

  it('maps business errors and calls the 401 handler', async () => {
    setToken({ accessToken: 'jwt-3', expiresIn: 7200, userId: 7 });
    const onUnauthorized = vi.fn();
    setUnauthorizedHandler(onUnauthorized);
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(json({ code: 401, message: '未登录或登录已过期', data: null }, 401)));
    const err = await request('/api/v1/datasets').catch((e: unknown) => e);
    expect(err).toBeInstanceOf(ApiError);
    expect((err as ApiError).message).toBe('未登录或登录已过期');
    expect(onUnauthorized).toHaveBeenCalledTimes(1);
  });

  it('reports network failures in plain language', async () => {
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new TypeError('Failed to fetch')));
    await expect(request('/api/v1/datasets', { anonymous: true })).rejects.toMatchObject({ code: 'NETWORK' });
  });

  it('refreshes the token shortly before it expires', async () => {
    setToken({ accessToken: 'old', expiresIn: 60, userId: 7 });
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(json({ code: 200, data: { accessToken: 'new', tokenType: 'Bearer', expiresIn: 7200, userId: 7 } }))
      .mockResolvedValueOnce(json({ code: 200, data: [] }));
    vi.stubGlobal('fetch', fetchMock);
    await request('/api/v1/datasets');
    expect(fetchMock.mock.calls[0][0]).toBe('/api/v1/auth/refresh');
    expect(fetchMock.mock.calls[1][1].headers).toMatchObject({ satoken: 'new' });
  });

  it('builds query strings without empty values', () => {
    expect(withQuery('/x', { a: 1, b: '', c: undefined, d: 'z z' })).toBe('/x?a=1&d=z+z');
  });
});

describe('SSE parsing', () => {
  it('splits frames and keeps the incomplete tail', () => {
    const { frames, rest } = parseSseFrames('event: answer_delta\ndata: {"text":"你"}\n\nevent: answer_delta\ndata: {"te');
    expect(frames).toEqual([{ event: 'answer_delta', data: '{"text":"你"}' }]);
    expect(rest).toBe('event: answer_delta\ndata: {"te');
  });
});

describe('answer mapping', () => {
  it('extracts [片段N] citations into blocks', () => {
    const blocks = blocksFromAnswer('第一项是多模态解析[片段1]。\n\n第二项[片段2][片段3]，第三项无引用');
    expect(blocks).toEqual([
      { kind: 'p', text: '第一项是多模态解析。', cite: [1] },
      { kind: 'p', text: '第二项，第三项无引用', cite: [2, 3] },
    ]);
  });

  it('numbers hits from 1 and keeps full content', () => {
    const [c] = toChunks([{ chunk_id: 'c1', doc_id: 9, dataset_id: 3, file_name: '手册.pdf', fused_score: 0.4, rerank_score: 0.91, content: '正文' }]);
    expect(c).toMatchObject({ n: 1, fileId: '9', datasetId: '3', fileName: '手册.pdf', fileType: 'PDF', score: 0.91, full: '正文' });
  });
});

describe('backend DTO mapping', () => {
  it('maps datasets with stats and status', () => {
    const ds = toDataset({
      id: 12,
      name: '产品库',
      description: null,
      status: 'DISABLED',
      createdAt: '2026-09-01T10:00:00',
      updatedAt: '2026-09-01T10:00:00',
      stats: { fileCount: 3, uploadingCount: 0, failedCount: 0, storageBytes: 2048, chunkCount: 40 },
    });
    expect(ds).toMatchObject({ id: '12', status: 'disabled', chunkCount: 40, storage: '2 KB', createdAt: '2026-09-01' });
  });

  it('combines upload and parse status for files', () => {
    const dto = { id: 5, datasetId: 12, originalFilename: 'a.md', fileSuffix: 'md', fileSize: 10, uploadStatus: 'UPLOAD_SUCCESS' as const, isUploadSuccess: true, failureReason: null, createdAt: '', updatedAt: '' };
    expect(toFile(dto, { fileId: 5, originalFilename: 'a.md', frontendStatus: 'parse_success', parseStatus: 'success', failureReason: null }).status).toBe('done');
    expect(toFile(dto, { fileId: 5, originalFilename: 'a.md', frontendStatus: 'parse_failed', parseStatus: 'failed', failureReason: 'bad' })).toMatchObject({ status: 'failed', note: 'bad' });
    expect(toFile({ ...dto, uploadStatus: 'UPLOADING' }).status).toBe('uploading');
  });

  it('groups model configs by provider and resolves defaults', () => {
    const base = { providerId: 1, iconUrl: null, protocol: 'openai', apiBaseUrl: null, isActive: true, editable: false, displayName: null };
    const state = toModelState(
      [
        { ...base, configId: 1, scope: 'SYSTEM', providerType: 'linkrag', providerName: 'LinkRAG', modelName: 'bge-m3', capability: 'EMBEDDING', apiKeyMasked: null },
        { ...base, configId: 2, scope: 'USER', providerType: 'deepseek', providerName: 'DeepSeek', modelName: 'deepseek-chat', capability: 'CHAT', apiKeyMasked: 'sk-****1234', editable: true },
      ],
      [
        { capability: 'CHAT', configId: 2 },
        { capability: 'EMBEDDING', configId: 1 },
      ],
    );
    expect(state.providers.map((p) => p.id)).toEqual(['deepseek', 'linkrag']);
    expect(state.providers[0].maskedKey).toBe('sk-****1234');
    expect(state.defaults).toEqual({ chat: 'deepseek/deepseek-chat', dense: 'linkrag/bge-m3' });
  });

  it('formats relative times', () => {
    const now = new Date('2026-09-29T15:00:00');
    expect(displayTime('2026-09-29T09:05:00', now)).toBe('今天 09:05');
    expect(displayTime('2026-09-28T09:05:00', now)).toBe('昨天');
    expect(displayTime('2026-09-02T09:05:00', now)).toBe('09-02');
  });
});
