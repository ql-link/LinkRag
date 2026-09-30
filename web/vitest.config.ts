import react from '@vitejs/plugin-react';
import path from 'path';
import { defineConfig } from 'vitest/config';

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: { '@': path.resolve(__dirname, './src') },
  },
  test: {
    environment: 'jsdom',
    globals: true,
    setupFiles: ['./src/test/setup.ts'],
    css: false,
    // 单元测试固定走 Mock 数据，不受本机 .env.local（联调时 VITE_USE_MOCK=false）影响
    env: { VITE_USE_MOCK: 'true' },
  },
});
