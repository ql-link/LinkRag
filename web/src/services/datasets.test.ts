import { db } from '@/mock/db';

import { createDataset, deleteDataset, fileStats, updateDataset } from './datasets';

beforeEach(() => db.reset());

describe('dataset service (mock)', () => {
  it('computes file stats including hidden done files', () => {
    const s = fileStats('ds_7f3a91c2');
    expect(s.total).toBe(342);
    expect(s.failed).toBe(1);
    expect(s.done + s.running + s.failed).toBe(s.total);
  });

  it('creates, rejects duplicate names, updates and deletes', async () => {
    const ds = await createDataset({ name: '新库', description: '', denseModel: 'bge-m3', sparseModel: 'BM25' });
    expect(db.state.datasets[0].id).toBe(ds.id);
    await expect(createDataset({ name: '新库', description: '', denseModel: 'bge-m3', sparseModel: 'BM25' })).rejects.toThrow('已存在同名知识库');
    await updateDataset(ds.id, { status: 'disabled' });
    expect(db.state.datasets.find((d) => d.id === ds.id)?.status).toBe('disabled');
    await deleteDataset(ds.id);
    expect(db.state.datasets.some((d) => d.id === ds.id)).toBe(false);
  });
});
