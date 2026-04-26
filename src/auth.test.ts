// src/auth.test.ts
import { describe, it, expect } from 'vitest';
import { encryptCreds, decryptCreds } from './auth.js';
import type { Credentials } from './shared/abs/types.js';

const SECRET = 'a'.repeat(64); // 64 hex chars = 32 bytes
const CREDS: Credentials = { userId: 'test@example.com', password: 'secret123' };

describe('encryptCreds / decryptCreds', () => {
  it('round-trips valid credentials', () => {
    const token = encryptCreds(CREDS, SECRET);
    expect(decryptCreds(token, SECRET)).toEqual(CREDS);
  });

  it('returns null for wrong secret', () => {
    const token = encryptCreds(CREDS, SECRET);
    expect(decryptCreds(token, 'b'.repeat(64))).toBeNull();
  });

  it('returns null for tampered payload', () => {
    const token = encryptCreds(CREDS, SECRET);
    const tampered = token.slice(0, -4) + 'XXXX';
    expect(decryptCreds(tampered, SECRET)).toBeNull();
  });

  it('returns null for empty string', () => {
    expect(decryptCreds('', SECRET)).toBeNull();
  });

  it('produces different ciphertext each call (random IV)', () => {
    const t1 = encryptCreds(CREDS, SECRET);
    const t2 = encryptCreds(CREDS, SECRET);
    expect(t1).not.toBe(t2);
  });
});
