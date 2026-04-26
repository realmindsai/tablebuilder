// src/workflows/abs-tablebuilder.ts
import { workflow, type LibrettoWorkflowContext } from 'libretto';
import { runTablebuilder } from '../shared/abs/runner.js';
import { loadCredentials } from '../shared/abs/auth.js';
import type { Input, Output } from '../shared/abs/types.js';

export default workflow<Input, Output>(
  'abs-tablebuilder',
  async (ctx: LibrettoWorkflowContext, input: Input): Promise<Output> => {
    const creds = loadCredentials(); // reads from ~/.tablebuilder/.env for CLI use
    return runTablebuilder(ctx.page, creds, input);
  }
);
