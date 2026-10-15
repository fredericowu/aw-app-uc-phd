import '@testing-library/jest-dom/vitest';
import { afterEach } from 'vitest';
import { cleanup } from '@testing-library/react';

// Without this, the DOM from one `it()`'s render() survives into the next
// test in the same file — invisible with one render() per file (true of
// every test file here so far) and a "multiple elements found" error the
// moment a file has more than one.
afterEach(() => {
  cleanup();
});

// recharts' ResponsiveContainer (used by CategoryBars, rendered on every
// view this app has) needs one — jsdom doesn't ship it.
if (typeof globalThis.ResizeObserver === 'undefined') {
  globalThis.ResizeObserver = class ResizeObserver {
    observe() {}
    unobserve() {}
    disconnect() {}
  };
}
