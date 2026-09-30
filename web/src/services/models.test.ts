import { modelId } from '@/mock/models';

import { defaultUsages, maskKey, modelOptions, modelStore, removeProvider, saveProvider, setDefault, stats, testConnection, toggleModel } from './models';

beforeEach(() => modelStore.reset());

describe('models service (mock)', () => {
  it('matches the D1 seed: 4 providers, defaults per capability', () => {
    const s = modelStore.state;
    expect(s.providers.map((p) => p.name)).toEqual(['DeepSeek', '通义千问', '硅基流动', 'LinkRAG 默认']);
    expect(s.defaults.chat).toBe(modelId('deepseek', 'DeepSeek-V3'));
    expect(stats().providers).toBe(4);
  });

  it('groups chat options into personal / platform / unavailable (D4)', () => {
    const o = modelOptions('chat');
    expect(o.personal.map((m) => m.name)).toContain('Qwen-Max');
    expect(o.platform.map((m) => m.name)).toEqual(['LinkRAG Chat', 'LinkRAG Lite']);
    expect(o.unavailable.some((u) => u.model.name === 'Moonshot-v1-128k')).toBe(true);
  });

  it('switches default models, including vector capabilities', async () => {
    await setDefault('chat', modelId('qwen', 'Qwen-Max'));
    expect(modelStore.state.defaults.chat).toBe(modelId('qwen', 'Qwen-Max'));
    await setDefault('dense', modelId('siliconflow', 'bge-large-zh-v1.5'));
    expect(modelStore.state.defaults.dense).toBe(modelId('siliconflow', 'bge-large-zh-v1.5'));
    await expect(setDefault('dense', modelId('qwen', 'text-embedding-v3'))).rejects.toThrow('不可用');
  });

  it('prevents disabling or removing models in use as defaults', () => {
    expect(defaultUsages(modelId('deepseek', 'DeepSeek-V3'))).toEqual(['chat']);
    expect(() => toggleModel(modelId('deepseek', 'DeepSeek-V3'), false)).toThrow('默认模型');
    expect(() => removeProvider('deepseek')).toThrow('默认模型');
    toggleModel(modelId('deepseek', 'DeepSeek-R1'), false);
    expect(modelStore.state.models.find((m) => m.name === 'DeepSeek-R1')?.enabled).toBe(false);
  });

  it('tests connection and saves a new provider with a masked key only (D3)', async () => {
    expect((await testConnection('zhipu', 'bad')).ok).toBe(false);
    const key = 'sk-6f2c1234567890abcdefa91e';
    expect((await testConnection('zhipu', key)).ok).toBe(true);
    await saveProvider({ providerId: 'zhipu', apiKey: key, enabledModels: ['GLM-4-Plus', 'GLM-4-Air'] });
    const p = modelStore.state.providers.find((x) => x.id === 'zhipu');
    expect(p?.maskedKey).toBe(maskKey(key));
    expect(JSON.stringify(modelStore.state)).not.toContain(key);
    expect(modelStore.state.providers.at(-1)?.builtin).toBe(true);
    expect(modelStore.state.models.filter((m) => m.providerId === 'zhipu' && m.enabled).map((m) => m.name)).toEqual(['GLM-4-Plus', 'GLM-4-Air']);
  });
});
