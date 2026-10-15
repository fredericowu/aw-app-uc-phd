import '@testing-library/jest-dom/vitest';

// recharts' ResponsiveContainer (used by CategoryBars, rendered on every
// view this app has) needs one — jsdom doesn't ship it.
if (typeof globalThis.ResizeObserver === 'undefined') {
  globalThis.ResizeObserver = class ResizeObserver {
    observe() {}
    unobserve() {}
    disconnect() {}
  };
}
