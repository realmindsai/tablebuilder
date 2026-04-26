// src/shared/abs/response-capture.ts
import { writeFile } from 'fs/promises';
import type { Page } from 'playwright-core';

export async function trySaveViaResponse(
  page: Page,
  clickFn: () => Promise<void>,
  tmpPath: string,
  waitMs = 15000,
): Promise<boolean> {
  return new Promise<boolean>(async (resolve) => {
    let saved = false;

    const responseHandler = async (response: {
      headers: () => Record<string, string>;
      body: () => Promise<Buffer>;
      url: () => string;
    }) => {
      if (saved) return;
      const headers = response.headers();
      const disp = headers['content-disposition'] ?? '';
      const type = headers['content-type'] ?? '';
      if (disp.includes('attachment') || type.includes('csv') || type.includes('zip') || type.includes('excel')) {
        try {
          const body = await response.body();
          await writeFile(tmpPath, body);
          saved = true;
          console.log(`trySaveViaResponse: captured response, content-type=${type}, size=${body.length}`);
          resolve(true);
        } catch { /* ignore */ }
      }
    };

    page.on('response', responseHandler);

    const dlPromise = page.waitForEvent('download', { timeout: waitMs })
      .then(async dl => {
        if (!saved) {
          await dl.saveAs(tmpPath);
          saved = true;
          console.log('trySaveViaResponse: captured via download event');
          resolve(true);
        }
      })
      .catch(() => { /* timeout */ });

    await clickFn();
    await dlPromise;

    await new Promise(r => setTimeout(r, 2000));
    page.off('response', responseHandler);
    if (!saved) resolve(false);
  });
}
