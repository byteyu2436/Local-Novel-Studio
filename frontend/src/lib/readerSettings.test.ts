import { describe, expect, it } from "vitest";

import {
  DEFAULT_READER_SETTINGS,
  READER_SETTINGS_KEY,
  parseReaderSettings,
  readReaderSettings,
  readerArticleStyle,
  resetReaderSettings,
  writeReaderSettings,
} from "./readerSettings";

function memoryStorage(initial: Record<string, string> = {}) {
  const store = { ...initial };
  return {
    getItem: (key: string) => (key in store ? store[key] : null),
    setItem: (key: string, value: string) => {
      store[key] = value;
    },
    removeItem: (key: string) => {
      delete store[key];
    },
    snapshot: () => store,
  };
}

describe("reader settings", () => {
  it("persists font, line-height, and width locally", () => {
    const storage = memoryStorage();
    const saved = writeReaderSettings(
      { fontSize: 22, lineHeight: 2, contentWidth: 48 },
      storage,
    );
    expect(saved.fontSize).toBe(22);
    expect(JSON.parse(storage.snapshot()[READER_SETTINGS_KEY]).fontSize).toBe(22);
    expect(readReaderSettings(storage)).toEqual(saved);
    expect(readerArticleStyle(saved)).toEqual({
      fontSize: "22px",
      lineHeight: "2",
      maxWidth: "48rem",
    });
    expect(resetReaderSettings(storage)).toEqual(DEFAULT_READER_SETTINGS);
  });

  it("falls back to defaults when storage is missing or corrupt", () => {
    expect(readReaderSettings(memoryStorage())).toEqual(DEFAULT_READER_SETTINGS);
    const broken = memoryStorage({ [READER_SETTINGS_KEY]: "{not-json" });
    expect(readReaderSettings(broken)).toEqual(DEFAULT_READER_SETTINGS);
    expect(parseReaderSettings({ fontSize: 99, lineHeight: "x" }).fontSize).toBe(28);
    expect(parseReaderSettings({ fontSize: 99, lineHeight: "x" }).lineHeight).toBe(1.4);
  });
});
