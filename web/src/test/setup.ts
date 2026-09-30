import '@testing-library/jest-dom/vitest';

// jsdom 未实现 scrollIntoView
Element.prototype.scrollIntoView ??= () => {};
