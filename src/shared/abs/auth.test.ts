// src/shared/abs/auth.test.ts
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { loadCredentials } from './auth.js';

// Prevent dotenv from loading ~/.tablebuilder/.env during unit tests so env-var
// assertions remain hermetic regardless of what exists on the developer's machine.
vi.mock('dotenv', () => ({ config: vi.fn() }));

describe('loadCredentials', () => {
  const saved = {
    id: process.env.TABLEBUILDER_USER_ID,
    pw: process.env.TABLEBUILDER_PASSWORD,
  };

  beforeEach(() => {
    delete process.env.TABLEBUILDER_USER_ID;
    delete process.env.TABLEBUILDER_PASSWORD;
  });

  afterEach(() => {
    if (saved.id) process.env.TABLEBUILDER_USER_ID = saved.id;
    else delete process.env.TABLEBUILDER_USER_ID;
    if (saved.pw) process.env.TABLEBUILDER_PASSWORD = saved.pw;
    else delete process.env.TABLEBUILDER_PASSWORD;
  });

  it('returns credentials when both env vars are set', () => {
    process.env.TABLEBUILDER_USER_ID = 'testuser';
    process.env.TABLEBUILDER_PASSWORD = 'testpass';
    expect(loadCredentials()).toEqual({ userId: 'testuser', password: 'testpass' });
  });

  it('throws containing TABLEBUILDER_USER_ID when userId is missing', () => {
    process.env.TABLEBUILDER_PASSWORD = 'testpass';
    expect(() => loadCredentials()).toThrow('TABLEBUILDER_USER_ID');
  });

  it('throws containing TABLEBUILDER_PASSWORD when password is missing', () => {
    process.env.TABLEBUILDER_USER_ID = 'testuser';
    expect(() => loadCredentials()).toThrow('TABLEBUILDER_PASSWORD');
  });
});
