import { useEffect, useState } from "react";
import { Link, Navigate, useParams, useSearchParams } from "react-router-dom";

import { Button } from "@/components/ui/button";
import {
  canonKindLabel,
  loadCanonChapter,
  loadChapterVersion,
  loadNovelChapters,
  readerPath,
  resolveActiveChapter,
  tocItemLabel,
  type ReaderChapter,
  type ReaderToc,
} from "@/lib/reader";

export default function ReaderPage() {
  const { novelId = "", chapterId } = useParams();
  const [params] = useSearchParams();
  const versionId = params.get("version");
  const [toc, setToc] = useState<ReaderToc | null>(null);
  const [chapter, setChapter] = useState<ReaderChapter | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [tocOpen, setTocOpen] = useState(true);

  useEffect(() => {
    let cancelled = false;
    async function run() {
      setLoading(true);
      const result = await loadNovelChapters(novelId);
      if (cancelled) return;
      if ("error" in result) {
        setError(result.error);
        setToc(null);
        setLoading(false);
        return;
      }
      setToc(result);
      setError(null);
      setLoading(false);
    }
    void run();
    return () => {
      cancelled = true;
    };
  }, [novelId]);

  const active = toc ? resolveActiveChapter(toc, chapterId) : null;

  useEffect(() => {
    const id = active?.chapter_id;
    if (!id) return;
    const targetId = id;
    let cancelled = false;
    async function run() {
      const result = versionId
        ? await loadChapterVersion(targetId, versionId)
        : await loadCanonChapter(targetId);
      if (cancelled) return;
      if ("error" in result) {
        setError(result.error);
        setChapter(null);
        return;
      }
      setChapter(result);
      setError(null);
    }
    void run();
    return () => {
      cancelled = true;
    };
  }, [active?.chapter_id, versionId]);

  if (!loading && toc && active && active.chapter_id !== chapterId) {
    return <Navigate to={readerPath(toc.novel_id, active.chapter_id)} replace />;
  }

  const previewing = Boolean(chapter && !chapter.is_canon);

  return (
    <main className="mx-auto flex min-h-screen max-w-5xl flex-col gap-6 px-6 py-10">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="space-y-2">
          <p className="text-sm font-medium uppercase tracking-[0.18em] text-muted-foreground">
            阅读
          </p>
          <h1 className="text-3xl font-semibold tracking-tight">
            {toc?.novel_title ?? "小说阅读"}
          </h1>
        </div>
        <div className="flex flex-wrap gap-2">
          <Button
            type="button"
            variant="outline"
            size="sm"
            onClick={() => setTocOpen((open) => !open)}
          >
            {tocOpen ? "收起目录" : "展开目录"}
          </Button>
          <Button asChild variant="ghost" size="sm">
            <Link to="/">返回首页</Link>
          </Button>
        </div>
      </div>

      {loading ? <p className="text-sm text-muted-foreground">正在加载章节目录…</p> : null}
      {error ? <p className="text-sm text-destructive">{error}</p> : null}

      {toc ? (
        <div className="grid gap-6 md:grid-cols-[minmax(12rem,16rem)_1fr]">
          {tocOpen ? (
            <nav className="max-h-[70vh] overflow-y-auto rounded-md border border-input p-3">
              <p className="mb-2 text-sm font-medium">目录</p>
              <ol className="flex flex-col gap-1">
                {toc.chapters.map((item) => (
                  <li key={item.chapter_id}>
                    <Link
                      to={readerPath(toc.novel_id, item.chapter_id)}
                      className={`block rounded-md px-2 py-1 text-sm ${
                        item.chapter_id === active?.chapter_id
                          ? "bg-accent font-medium"
                          : "hover:bg-accent/60"
                      }`}
                    >
                      {tocItemLabel(item)}
                    </Link>
                  </li>
                ))}
              </ol>
            </nav>
          ) : (
            <div />
          )}
          <section className="min-h-[40vh] rounded-md border border-input px-4 py-6">
            {active && chapter && chapter.chapter_id === active.chapter_id ? (
              <>
                <div className="flex flex-wrap items-center justify-between gap-3">
                  <h2 className="text-xl font-semibold">{tocItemLabel(chapter)}</h2>
                  <span
                    className={`rounded-md px-2 py-1 text-xs font-medium ${
                      previewing
                        ? "bg-destructive/15 text-destructive"
                        : "bg-accent text-accent-foreground"
                    }`}
                  >
                    {canonKindLabel(chapter.version_kind, chapter.is_canon)}
                  </span>
                </div>
                {previewing ? (
                  <p className="mt-2 text-sm text-destructive">
                    当前是草稿/历史预览，不会覆盖 Canon 正文。
                    <Link
                      className="ml-2 underline"
                      to={readerPath(toc.novel_id, chapter.chapter_id)}
                    >
                      返回 Canon
                    </Link>
                  </p>
                ) : null}
                <article className="mt-4 max-h-[70vh] overflow-y-auto whitespace-pre-wrap text-base leading-8">
                  {chapter.body}
                </article>
                <div className="mt-6 flex flex-wrap gap-3">
                  {chapter.previous ? (
                    <Button asChild variant="outline">
                      <Link to={readerPath(toc.novel_id, chapter.previous.chapter_id)}>
                        上一章
                      </Link>
                    </Button>
                  ) : (
                    <Button variant="outline" disabled>
                      上一章
                    </Button>
                  )}
                  {chapter.next ? (
                    <Button asChild>
                      <Link to={readerPath(toc.novel_id, chapter.next.chapter_id)}>
                        下一章
                      </Link>
                    </Button>
                  ) : (
                    <Button disabled>下一章</Button>
                  )}
                </div>
              </>
            ) : active ? (
              <p className="text-sm text-muted-foreground">正在加载正文…</p>
            ) : (
              <p className="text-sm text-muted-foreground">这本小说还没有章节。</p>
            )}
          </section>
        </div>
      ) : null}
    </main>
  );
}
