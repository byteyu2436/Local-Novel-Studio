import { Link } from "react-router-dom";

import { Button } from "@/components/ui/button";
import { HOME_EYEBROW, HOME_TAGLINE, HOME_TITLE } from "@/pages/home";

export default function HomePage() {
  return (
    <main className="mx-auto flex min-h-screen max-w-3xl flex-col gap-8 px-6 py-16">
      <div className="space-y-3">
        <p className="text-sm font-medium uppercase tracking-[0.18em] text-muted-foreground">
          {HOME_EYEBROW}
        </p>
        <h1 className="text-4xl font-semibold tracking-tight">{HOME_TITLE}</h1>
        <p className="max-w-2xl text-lg leading-7 text-muted-foreground">
          {HOME_TAGLINE}
        </p>
      </div>
      <div>
        <Button asChild>
          <Link to="/diagnostics">打开系统健康页</Link>
        </Button>
      </div>
    </main>
  );
}
