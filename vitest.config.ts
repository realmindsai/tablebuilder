// vitest.config.ts
import { defineConfig } from 'vitest/config';

export default defineConfig({
  test: {
    // Include unit and integration tests under src/; exclude e2e by default.
    // Run e2e separately via: npm run test:e2e
    include: ['src/**/*.test.ts'],
    exclude: ['tests/**'],
  },
});
