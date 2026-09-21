export const READER_SETTINGS_KEY = "lns.reader-settings";

export type ReaderSettings = {
  fontSize: number;
  lineHeight: number;
  contentWidth: number;
};

export const DEFAULT_READER_SETTINGS: ReaderSettings = {
  fontSize: 18,
  lineHeight: 1.8,
  contentWidth: 42,
};

const LIMITS = {
  fontSize: { min: 14, max: 28 },
  lineHeight: { min: 1.4, max: 2.4 },
  contentWidth: { min: 28, max: 56 },
};

function clamp(value: number, min: number, max: number): number {
  if (Number.isNaN(value)) return min;
  return Math.min(max, Math.max(min, value));
}

export function parseReaderSettings(raw: unknown): ReaderSettings {
  if (!raw || typeof raw !== "object") return { ...DEFAULT_READER_SETTINGS };
  const body = raw as Partial<ReaderSettings>;
  return {
    fontSize: clamp(Number(body.fontSize), LIMITS.fontSize.min, LIMITS.fontSize.max),
    lineHeight: clamp(
      Number(body.lineHeight),
      LIMITS.lineHeight.min,
      LIMITS.lineHeight.max,
    ),
    contentWidth: clamp(
      Number(body.contentWidth),
      LIMITS.contentWidth.min,
      LIMITS.contentWidth.max,
    ),
  };
}

export function readReaderSettings(
  storage: Pick<Storage, "getItem"> = window.localStorage,
): ReaderSettings {
  try {
    const raw = storage.getItem(READER_SETTINGS_KEY);
    if (!raw) return { ...DEFAULT_READER_SETTINGS };
    return parseReaderSettings(JSON.parse(raw));
  } catch {
    return { ...DEFAULT_READER_SETTINGS };
  }
}

export function writeReaderSettings(
  settings: ReaderSettings,
  storage: Pick<Storage, "setItem"> = window.localStorage,
): ReaderSettings {
  const next = parseReaderSettings(settings);
  try {
    storage.setItem(READER_SETTINGS_KEY, JSON.stringify(next));
  } catch {
    return next;
  }
  return next;
}

export function resetReaderSettings(
  storage: Pick<Storage, "removeItem" | "setItem"> = window.localStorage,
): ReaderSettings {
  try {
    storage.removeItem(READER_SETTINGS_KEY);
  } catch {
    /* ignore quota / private mode */
  }
  return writeReaderSettings(DEFAULT_READER_SETTINGS, storage);
}

export function readerArticleStyle(settings: ReaderSettings): {
  fontSize: string;
  lineHeight: string;
  maxWidth: string;
} {
  return {
    fontSize: `${settings.fontSize}px`,
    lineHeight: String(settings.lineHeight),
    maxWidth: `${settings.contentWidth}rem`,
  };
}
