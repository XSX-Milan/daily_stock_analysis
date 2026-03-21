import { defineConfig, devices } from '@playwright/test';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const currentDir = path.dirname(fileURLToPath(import.meta.url));
const repoRoot = path.resolve(currentDir, '../..');
const smokeBackendOrigin = process.env.DSA_WEB_SMOKE_BACKEND_ORIGIN ?? 'http://127.0.0.1:8000';

function resolveBackendCommand(backendOrigin: string) {
  const backendUrl = new URL(backendOrigin);
  const backendHost = backendUrl.hostname;
  const backendPort = backendUrl.port || (backendUrl.protocol === 'https:' ? '443' : '80');

  if (process.env.DSA_WEB_SMOKE_BACKEND_CMD) {
    return process.env.DSA_WEB_SMOKE_BACKEND_CMD;
  }

  const unixVenvPython = path.join(repoRoot, '.venv', 'bin', 'python');
  if (fs.existsSync(unixVenvPython)) {
    return `${unixVenvPython} main.py --webui-only --host ${backendHost} --port ${backendPort}`;
  }

  const windowsVenvPython = path.join(repoRoot, '.venv', 'Scripts', 'python.exe');
  if (fs.existsSync(windowsVenvPython)) {
    return `"${windowsVenvPython}" main.py --webui-only --host ${backendHost} --port ${backendPort}`;
  }

  return `python main.py --webui-only --host ${backendHost} --port ${backendPort}`;
}

export default defineConfig({
  testDir: './e2e',
  fullyParallel: false,
  retries: process.env.CI ? 2 : 0,
  reporter: 'list',
  use: {
    baseURL: 'http://127.0.0.1:4173',
    trace: 'on-first-retry',
    screenshot: 'only-on-failure',
    video: 'retain-on-failure',
  },
  webServer: [
    {
      command: resolveBackendCommand(smokeBackendOrigin),
      cwd: repoRoot,
      url: `${smokeBackendOrigin}/api/v1/auth/status`,
      reuseExistingServer: !process.env.CI,
      timeout: 120_000,
    },
    {
      command: 'npm run dev -- --host 127.0.0.1 --port 4173',
      cwd: currentDir,
      url: 'http://127.0.0.1:4173',
      reuseExistingServer: !process.env.CI,
      timeout: 120_000,
    },
  ],
  projects: [
    {
      name: 'chromium',
      use: { ...devices['Desktop Chrome'] },
    },
  ],
});
