import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import tailwindcss from '@tailwindcss/vite';

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    port: 5173,
    strictPort: true,
    proxy: Object.fromEntries(
      ['/v1', '/health', '/auth'].map((path) => [
        path,
        {
          target: 'http://127.0.0.1:8000',
          changeOrigin: false,
        },
      ]),
    ),
  },
  preview: { port: 5173, strictPort: true },
});
