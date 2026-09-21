export type ReaderTocItem = {
  chapter_id: string;
  sequence: number;
  original_label: string;
  display_title: string;
  title_source: string;
  canon_kind: string | null;
  has_draft: boolean;
};

export type ReaderToc = {
  novel_id: string;
  novel_title: string;
  chapters: ReaderTocItem[];
};

export function readerPath(
  novelId: string,
  chapterId?: string,
  versionId?: string,
): string {
  if (!chapterId) return `/novels/${novelId}`;
  const base = `/novels/${novelId}/chapters/${chapterId}`;
  if (versionId) return `${base}?version=${encodeURIComponent(versionId)}`;
  return base;
}

export function readingChapterPath(novelId: string, chapterId: string): string {
  return readerPath(novelId, chapterId);
}

export function tocItemLabel(
  item: Pick<ReaderTocItem, "sequence" | "display_title">,
): string {
  const title = item.display_title.trim() || `第${item.sequence}章`;
  if (title.startsWith(`第${item.sequence}章`)) return title;
  return `${item.sequence}. ${title}`;
}

export function resolveActiveChapter(
  toc: ReaderToc,
  chapterId: string | undefined,
): ReaderTocItem | null {
  if (toc.chapters.length === 0) return null;
  if (chapterId) {
    const match = toc.chapters.find((item) => item.chapter_id === chapterId);
    if (match) return match;
  }
  return toc.chapters[0];
}

export function parseTocPayload(payload: unknown): ReaderToc | { error: string } {
  if (!payload || typeof payload !== "object") {
    return { error: "无法读取章节目录。" };
  }
  const body = payload as Partial<ReaderToc>;
  if (typeof body.novel_id !== "string" || !Array.isArray(body.chapters)) {
    return { error: "无法读取章节目录。" };
  }
  return {
    novel_id: body.novel_id,
    novel_title: typeof body.novel_title === "string" ? body.novel_title : "未命名小说",
    chapters: body.chapters.filter(
      (item): item is ReaderTocItem =>
        Boolean(item) &&
        typeof item.chapter_id === "string" &&
        typeof item.sequence === "number",
    ),
  };
}

export async function loadNovelChapters(
  novelId: string,
  fetcher: typeof fetch = fetch,
): Promise<ReaderToc | { error: string }> {
  const response = await fetcher(`/api/novels/${novelId}/chapters`);
  const payload: unknown = await response.json().catch(() => null);
  if (!response.ok) {
    return { error: "章节目录加载失败，请确认小说是否存在。" };
  }
  return parseTocPayload(payload);
}

export type ChapterNav = {
  chapter_id: string;
  sequence: number;
  display_title: string;
};

export type ReaderChapter = {
  novel_id: string;
  chapter_id: string;
  sequence: number;
  original_label: string;
  original_title: string;
  display_title: string;
  title_source: string;
  body: string;
  version_id: string;
  version_kind: string;
  is_canon: boolean;
  has_draft: boolean;
  previous: ChapterNav | null;
  next: ChapterNav | null;
};

export function canonKindLabel(kind: string | null, isCanon: boolean): string {
  if (!isCanon) {
    if (kind === "DRAFT") return "草稿预览，不是当前 Canon";
    return "历史版本预览，不是当前 Canon";
  }
  if (kind === "ACCEPTED") return "已采纳 Canon";
  return "原文 Canon";
}

export function navDisabled(
  direction: "previous" | "next",
  chapter: ReaderChapter,
): boolean {
  return direction === "previous" ? chapter.previous === null : chapter.next === null;
}

function parseNav(value: unknown): ChapterNav | null {
  if (!value || typeof value !== "object") return null;
  const body = value as Partial<ChapterNav>;
  if (typeof body.chapter_id !== "string") return null;
  return {
    chapter_id: body.chapter_id,
    sequence: typeof body.sequence === "number" ? body.sequence : 0,
    display_title: typeof body.display_title === "string" ? body.display_title : "",
  };
}

export function parseCanonPayload(payload: unknown): ReaderChapter | { error: string } {
  if (!payload || typeof payload !== "object") {
    return { error: "无法读取章节正文。" };
  }
  const body = payload as Partial<ReaderChapter>;
  if (typeof body.chapter_id !== "string" || typeof body.body !== "string") {
    return { error: "无法读取章节正文。" };
  }
  return {
    novel_id: typeof body.novel_id === "string" ? body.novel_id : "",
    chapter_id: body.chapter_id,
    sequence: typeof body.sequence === "number" ? body.sequence : 0,
    original_label: typeof body.original_label === "string" ? body.original_label : "",
    original_title: typeof body.original_title === "string" ? body.original_title : "",
    display_title: typeof body.display_title === "string" ? body.display_title : "",
    title_source: typeof body.title_source === "string" ? body.title_source : "fallback",
    body: body.body,
    version_id: typeof body.version_id === "string" ? body.version_id : "",
    version_kind: typeof body.version_kind === "string" ? body.version_kind : "ORIGINAL",
    is_canon: body.is_canon === true,
    has_draft: body.has_draft === true,
    previous: parseNav(body.previous),
    next: parseNav(body.next),
  };
}

export async function loadCanonChapter(
  chapterId: string,
  fetcher: typeof fetch = fetch,
): Promise<ReaderChapter | { error: string }> {
  const response = await fetcher(`/api/chapters/${chapterId}`);
  const payload: unknown = await response.json().catch(() => null);
  if (!response.ok) {
    return { error: "章节正文加载失败。" };
  }
  return parseCanonPayload(payload);
}

export async function loadChapterVersion(
  chapterId: string,
  versionId: string,
  fetcher: typeof fetch = fetch,
): Promise<ReaderChapter | { error: string }> {
  const [canon, versionResponse] = await Promise.all([
    loadCanonChapter(chapterId, fetcher),
    fetcher(`/api/chapters/${chapterId}/versions/${versionId}`),
  ]);
  if ("error" in canon) return canon;
  const payload: unknown = await versionResponse.json().catch(() => null);
  if (!versionResponse.ok) {
    return { error: "指定版本无法预览。" };
  }
  if (!payload || typeof payload !== "object") {
    return { error: "指定版本无法预览。" };
  }
  const body = payload as {
    body?: string;
    version_id?: string;
    version_kind?: string;
    is_canon?: boolean;
  };
  if (typeof body.body !== "string") {
    return { error: "指定版本无法预览。" };
  }
  return {
    ...canon,
    body: body.body,
    version_id: typeof body.version_id === "string" ? body.version_id : versionId,
    version_kind: typeof body.version_kind === "string" ? body.version_kind : "DRAFT",
    is_canon: body.is_canon === true,
  };
}
