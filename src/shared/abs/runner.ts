// src/shared/abs/runner.ts
import type { Page } from 'playwright-core';
import { login } from './auth.js';
import { selectDataset, selectVariables } from './navigator.js';
import { retrieveTable } from './jsf.js';
import { downloadCsv } from './downloader.js';
import { noopReporter, NEVER_ABORT, CancelledError, type PhaseReporter } from './reporter.js';
import type { Credentials, Input, Output } from './types.js';

export async function runTablebuilder(
  page: Page,
  creds: Credentials,
  input: Input,
  reporter: PhaseReporter = noopReporter,
  signal: AbortSignal = NEVER_ABORT,
): Promise<Output> {
  try {
    await login(page, creds, reporter, signal);

    if (signal.aborted) throw new CancelledError();

    const resolvedDataset = await selectDataset(page, input.dataset, reporter, signal);
    await selectVariables(page, {
      rows: input.rows,
      columns: input.columns,
      wafers: input.wafers ?? [],
    }, reporter, signal);

    if (signal.aborted) throw new CancelledError();

    await retrieveTable(page, reporter, signal);
    const { csvPath, rowCount } = await downloadCsv(page, input.outputPath, reporter);

    const result = { csvPath, dataset: resolvedDataset, rowCount };
    reporter({ type: 'complete', result });
    return result;
  } catch (err) {
    if (err instanceof CancelledError) throw err;
    const message = err instanceof Error ? err.message : String(err);
    reporter({ type: 'error', message });
    throw err;
  }
}
