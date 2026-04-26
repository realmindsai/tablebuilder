// src/shared/abs/jsf.test.ts
import { describe, it, expect, vi } from 'vitest';
import type { Page } from 'playwright-core';
import { submitJsfForm } from './jsf.js';

function makeMockPage(): Page {
  return {
    evaluate: vi.fn().mockResolvedValue(undefined),
    waitForLoadState: vi.fn().mockResolvedValue(undefined),
  } as unknown as Page;
}

describe('submitJsfForm', () => {
  it('calls page.evaluate once for row axis', async () => {
    const page = makeMockPage();
    await submitJsfForm(page, 'row');
    expect(page.evaluate).toHaveBeenCalledOnce();
  });

  it('passes #buttonForm\\:addR selector for row axis', async () => {
    const page = makeMockPage();
    await submitJsfForm(page, 'row');
    const [, arg] = (page.evaluate as ReturnType<typeof vi.fn>).mock.calls[0] as [unknown, string];
    expect(arg).toBe('#buttonForm\\:addR');
  });

  it('passes #buttonForm\\:addC selector for col axis', async () => {
    const page = makeMockPage();
    await submitJsfForm(page, 'col');
    const [, arg] = (page.evaluate as ReturnType<typeof vi.fn>).mock.calls[0] as [unknown, string];
    expect(arg).toBe('#buttonForm\\:addC');
  });

  it('passes #buttonForm\\:addL selector for wafer axis', async () => {
    const page = makeMockPage();
    await submitJsfForm(page, 'wafer');
    const [, arg] = (page.evaluate as ReturnType<typeof vi.fn>).mock.calls[0] as [unknown, string];
    expect(arg).toBe('#buttonForm\\:addL');
  });

  it('calls waitForLoadState after evaluate', async () => {
    const page = makeMockPage();
    await submitJsfForm(page, 'row');
    expect(page.waitForLoadState).toHaveBeenCalledWith('load', { timeout: 15000 });
  });
});
