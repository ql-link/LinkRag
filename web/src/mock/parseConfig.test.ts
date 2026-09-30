import { clone, DEFAULT_CONFIG, diffKeys, validateConfig } from './parseConfig';

describe('parse config', () => {
  it('default config is valid and has no diff', () => {
    expect(validateConfig(DEFAULT_CONFIG)).toEqual({});
    expect(diffKeys(DEFAULT_CONFIG, clone(DEFAULT_CONFIG))).toEqual([]);
  });

  it('reports nested diffs', () => {
    const c = clone(DEFAULT_CONFIG);
    c.chunkMaxTokens = 640;
    c.channels.sparse = false;
    expect(diffKeys(c, DEFAULT_CONFIG).sort()).toEqual(['channels.sparse', 'chunkMaxTokens']);
  });

  it('requires positive weight across enabled channels (C9)', () => {
    const c = clone(DEFAULT_CONFIG);
    c.channels = { bm25: true, sparse: false, dense: true };
    c.weights = { bm25: 0, sparse: 0.5, dense: 0 };
    expect(validateConfig(c).weights).toBe('启用通道的总权重需大于 0');
  });

  it('checks chunk bounds relative to each other', () => {
    const c = clone(DEFAULT_CONFIG);
    c.chunkMinTokens = 600;
    c.forceSplitTokens = 400;
    const e = validateConfig(c);
    expect(e.chunkMinTokens).toBeDefined();
    expect(e.forceSplitTokens).toBeDefined();
  });
});
