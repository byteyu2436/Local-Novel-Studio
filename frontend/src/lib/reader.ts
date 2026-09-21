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

export function readerPath(novelId: string, chapterId?: string): string {
  if (!chapterId) return `/novels/${novelId}`;
  return `/novels/${novelId}/chapters/${chapterId}`;
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
