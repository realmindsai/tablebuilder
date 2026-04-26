// src/auth.ts
import { createCipheriv, createDecipheriv, randomBytes } from 'crypto';
import type { Credentials } from './shared/abs/types.js';

const ALGO = 'aes-256-gcm';

// Binary layout: [iv: 12 bytes][tag: 16 bytes][ciphertext: variable]
// Encoded as base64url for safe use in cookie values.

export function encryptCreds(creds: Credentials, secret: string): string {
  const key = Buffer.from(secret, 'hex');
  const iv = randomBytes(12);
  const cipher = createCipheriv(ALGO, key, iv);
  const payload = JSON.stringify({ userId: creds.userId, password: creds.password });
  const encrypted = Buffer.concat([cipher.update(payload, 'utf8'), cipher.final()]);
  const tag = cipher.getAuthTag();
  return Buffer.concat([iv, tag, encrypted]).toString('base64url');
}

export function decryptCreds(token: string, secret: string): Credentials | null {
  try {
    const key = Buffer.from(secret, 'hex');
    const data = Buffer.from(token, 'base64url');
    if (data.length < 29) return null; // minimum: 12 iv + 16 tag + 1 byte payload
    const iv = data.subarray(0, 12);
    const tag = data.subarray(12, 28);
    const encrypted = data.subarray(28);
    const decipher = createDecipheriv(ALGO, key, iv);
    decipher.setAuthTag(tag);
    const decrypted = Buffer.concat([decipher.update(encrypted), decipher.final()]);
    const parsed = JSON.parse(decrypted.toString('utf8')) as Record<string, unknown>;
    if (typeof parsed.userId !== 'string' || typeof parsed.password !== 'string') return null;
    return { userId: parsed.userId, password: parsed.password };
  } catch {
    return null;
  }
}
