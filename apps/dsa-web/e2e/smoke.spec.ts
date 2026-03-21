import { expect, test, type Page } from '@playwright/test';

const smokePassword = process.env.DSA_WEB_SMOKE_PASSWORD;

type AuthStatus = {
  authEnabled: boolean;
  loggedIn: boolean;
};

async function fetchAuthStatus(page: Page): Promise<AuthStatus> {
  const response = await page.request.get('/api/v1/auth/status');
  expect(response.ok()).toBeTruthy();
  return (await response.json()) as AuthStatus;
}

async function login(page: Page) {
  const authStatus = await fetchAuthStatus(page);

  if (!authStatus.authEnabled) {
    await page.goto('/');
    await page.waitForLoadState('domcontentloaded');
    await page.waitForTimeout(1000);
    return;
  }

  if (authStatus.loggedIn) {
    await page.goto('/');
    await page.waitForLoadState('domcontentloaded');
    await page.waitForTimeout(1000);
    return;
  }

  test.skip(!smokePassword, 'Set DSA_WEB_SMOKE_PASSWORD to run authenticated smoke tests.');

  // Navigate to login page
  await page.goto('/login');
  await page.waitForLoadState('domcontentloaded');

  // Wait for password input to be visible
  await expect(page.locator('#password')).toBeVisible({ timeout: 10_000 });

  // Fill password and submit
  await page.locator('#password').fill(smokePassword!);

  // Wait for and click the submit button
  const submitButton = page.getByRole('button', { name: /授权进入工作台|完成设置并登录/ });
  await expect(submitButton).toBeVisible();

  await Promise.all([
    page.waitForResponse(
      (response) => response.url().includes('/api/v1/auth/login') && response.status() === 200,
      { timeout: 15_000 }
    ),
    submitButton.click(),
  ]);

  // Wait for navigation to home page after login
  await page.waitForURL('/', { timeout: 15_000 });
  await page.waitForLoadState('domcontentloaded');
  await page.waitForTimeout(1000);
}

test.describe('web smoke', () => {
  test('login page renders password form', async ({ page }) => {
    const authStatus = await fetchAuthStatus(page);

    await page.goto('/login');
    await page.waitForLoadState('domcontentloaded');

    if (!authStatus.authEnabled) {
      await page.waitForURL('/', { timeout: 15_000 });
      await expect(page.getByTestId('home-dashboard')).toBeVisible({ timeout: 10_000 });
      await expect(page.getByPlaceholder('输入股票代码或名称，如 600519、贵州茅台、AAPL')).toBeVisible();
      return;
    }

    // Check for branding
    await expect(page.getByText('DAILY STOCK').first()).toBeVisible();
    await expect(page.getByText('Analysis Engine')).toBeVisible();

    // Check for password input
    await expect(page.locator('#password')).toBeVisible();

    // Check for submit button
    await expect(page.getByRole('button', { name: /授权进入工作台|完成设置并登录/ })).toBeVisible();
  });

  test('homepage ignores legacy recommendation deep links', async ({ page }) => {
    await login(page);

    await page.goto('/?from=rec-history&query_id=rec_600519_20260321_1');
    await page.waitForLoadState('domcontentloaded');

    await expect(page.getByTestId('home-dashboard')).toBeVisible({ timeout: 10_000 });
    await expect(page.getByPlaceholder('输入股票代码或名称，如 600519、贵州茅台、AAPL')).toBeVisible();
    await expect(page.getByTestId('recommendation-detail-drawer')).toHaveCount(0);
    expect(new URL(page.url()).pathname).toBe('/');
  });

  test('recommendation page loads and isolates detail viewing locally', async ({ page }) => {
    await login(page);

    await page.goto('/recommend');
    await page.waitForLoadState('domcontentloaded');

    await expect(page.getByTestId('recommend-page')).toBeVisible({ timeout: 10_000 });
    await expect(page.getByTestId('recommendation-table')).toBeVisible({ timeout: 10_000 });

    const recommendationRows = page.locator('[data-testid^="table-row-"]');
    const rowCount = await recommendationRows.count();
    test.skip(rowCount === 0, 'No recommendation rows available to open local detail drawer.');

    await recommendationRows.first().click();
    await expect(page.getByTestId('recommendation-detail-drawer')).toBeVisible({ timeout: 15_000 });
    expect(new URL(page.url()).pathname).toBe('/recommend');

    await page.getByRole('button', { name: '关闭抽屉' }).click();
    await expect(page.getByTestId('recommendation-detail-drawer')).toHaveCount(0);
    expect(new URL(page.url()).pathname).toBe('/recommend');
  });

  test('home page shows analysis entry and history panel after login', async ({ page }) => {
    await login(page);

    const stockInput = page.getByPlaceholder('输入股票代码或名称，如 600519、贵州茅台、AAPL');
    await expect(stockInput).toBeVisible({ timeout: 10_000 });
    await expect(page.getByRole('link', { name: '首页' })).toBeVisible();
    await expect(page.getByRole('link', { name: '问股' })).toBeVisible();
    await expect(page.getByText('历史分析')).toBeVisible();

    await stockInput.fill('600519');
    const analyzeButton = page.getByRole('button', { name: '分析', exact: true });
    await expect(analyzeButton).toBeVisible();
  });

  test('chat page allows entering a question and starts a request', async ({ page }) => {
    await login(page);

    // Navigate to chat page by clicking the link
    await page.getByRole('link', { name: '问股' }).click();
    await page.waitForLoadState('domcontentloaded');
    await page.waitForTimeout(1000);

    await expect(page.getByTestId('chat-workspace')).toBeVisible({ timeout: 10_000 });
    await expect(page.getByTestId('chat-session-list-scroll')).toBeVisible();
    await expect(page.getByTestId('chat-message-scroll')).toBeVisible();

    const input = page.getByPlaceholder(/分析 600519/);
    await expect(input).toBeVisible({ timeout: 5000 });
    await expect(page.getByText('策略', { exact: true })).toBeVisible();

    const prompt = '请简要分析 600519';
    await input.fill(prompt);
    await page.getByRole('button', { name: '发送' }).click();

    await expect(page.locator('p').filter({ hasText: prompt }).last()).toBeVisible({ timeout: 5000 });
  });

  test('mobile shell opens navigation drawer after login', async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    await login(page);

    // Try to open navigation menu
    const menuButton = page.getByRole('button', { name: /打开导航|菜单/i });
    if (await menuButton.isVisible({ timeout: 2000 }).catch(() => false)) {
      await menuButton.click();
    }

    // Check if navigation is visible
    await expect(page.getByRole('link', { name: '回测' })).toBeVisible({ timeout: 5000 });
  });

  test('settings page renders title and save actions after login', async ({ page }) => {
    await login(page);

    // Navigate to settings page by clicking the link
    await page.getByRole('link', { name: '设置' }).click();
    await page.waitForLoadState('domcontentloaded');
    await page.waitForTimeout(1000);

    // Use heading role for more precise selection
    await expect(page.getByRole('heading', { name: '系统设置' })).toBeVisible({ timeout: 10_000 });
    await expect(page.getByRole('button', { name: '重置' })).toBeVisible();
    await expect(page.getByRole('button', { name: /保存配置/ })).toBeVisible();
  });

  test('backtest page renders filter controls after login', async ({ page }) => {
    await login(page);

    // Navigate to backtest page by clicking the link
    await page.getByRole('link', { name: '回测' }).click();
    await page.waitForLoadState('domcontentloaded');
    await page.waitForTimeout(1000);

    // Check for filter controls
    const filterInput = page.getByPlaceholder(/stock code/i);
    await expect(filterInput).toBeVisible({ timeout: 10_000 });
    await expect(page.getByRole('button', { name: /filter/i })).toBeVisible();
    await expect(page.getByRole('button', { name: /run backtest/i })).toBeVisible();
  });
});
