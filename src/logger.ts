// src/logger.ts
import { mkdir, appendFile, readdir, unlink } from 'fs/promises';
import { join } from 'path';
import { homedir } from 'os';

// Read at call time (not module load) so _TEST_LOG_DIR env override works in tests.
function getLogDir(): string {
  return process.env._TEST_LOG_DIR ?? join(homedir(), '.tablebuilder', 'logs');
}

export interface AuditEntry {
  ts: string;
  absUsername: string;
  clientIP: string;
  dataset: string;
  rows: string[];
  cols: string[];
  wafers: string[];
  status: 'success' | 'error' | 'cancelled';
  durationMs: number;
  rowCount: number | null;
  errorMsg?: string;
}

export async function logRun(entry: AuditEntry): Promise<void> {
  const dir = getLogDir();
  await mkdir(dir, { recursive: true });
  const date = new Date().toISOString().slice(0, 10);
  const file = join(dir, `${date}.jsonl`);
  await appendFile(file, JSON.stringify(entry) + '\n');
}

export async function pruneOldLogs(retentionDays = 30): Promise<void> {
  const dir = getLogDir();
  await mkdir(dir, { recursive: true });
  const cutoff = new Date();
  cutoff.setDate(cutoff.getDate() - retentionDays);
  let files: string[];
  try {
    files = await readdir(dir);
  } catch {
    return;
  }
  for (const file of files) {
    if (!file.endsWith('.jsonl')) continue;
    const dateStr = file.slice(0, 10);
    if (!Number.isNaN(Date.parse(dateStr)) && new Date(dateStr) < cutoff) {
      await unlink(join(dir, file)).catch(() => null);
    }
  }
}
