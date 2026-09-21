import { useEffect, useState } from "react";
import { Link, Navigate, useParams } from "react-router-dom";

import { Button } from "@/components/ui/button";
import {
  loadNovelChapters,
  readerPath,
  resolveActiveChapter,
  tocItemLabel,
  type ReaderToc,
} from "@/lib/reader";

export default function ReaderPage() {
  const { novelId = "", chapterId } = useParams();
  const [toc, setToc] = useState<ReaderToc | null>(null);
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
  if (!loading && toc && active && active.chapter_id !== chapterId) {
    return <Navigate to={readerPath(toc.novel_id, active.chapter_id)} replace />;
  }

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
          <section className="min-h-[40vh] rounded-md border border-dashed px-4 py-6">
            {active ? (
              <>
                <h2 className="text-xl font-semibold">{tocItemLabel(active)}</h2>
                <p className="mt-3 text-sm text-muted-foreground">
                  已定位到本章。正文视图将在后续步骤加载 Canon 内容。
                </p>
              </>
            ) : (
              <p className="text-sm text-muted-foreground">这本小说还没有章节。</p>
            )}
          </section>
        </div>
      ) : null}
    </main>
  );
}
