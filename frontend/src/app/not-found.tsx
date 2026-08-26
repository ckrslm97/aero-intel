import { Compass, Home } from "lucide-react";
import Link from "next/link";

// Faz 12: the app called notFound() (see app/newspaper/[date]/page.tsx)
// without ever having a styled page for it -- every 404 fell through to
// Next's own default, off-brand "This page could not be found." This is the
// six-page nav's own visual language, not a generic error template.
export default function NotFound() {
  return (
    <div className="flex min-h-[60vh] flex-col items-center justify-center gap-5 text-center">
      <span
        aria-hidden
        style={{ "--glow-color": "var(--primary)" } as React.CSSProperties}
        className="flex size-16 items-center justify-center rounded-full bg-gradient-to-br from-primary/15 to-chart-4/20 text-primary ring-1 ring-primary/15 dark:from-primary/25 dark:to-chart-4/30 dark:ring-primary/35 dark:glow"
      >
        <Compass className="size-8" />
      </span>
      <div className="flex flex-col gap-1.5">
        <h1 className="text-2xl font-semibold tracking-tight">
          Bu rota <span className="gradient-text">bilinmiyor</span>
        </h1>
        <p className="max-w-sm text-sm leading-relaxed text-muted-foreground">
          Aradığınız sayfa taşınmış ya da hiç var olmamış olabilir. Menüden altı ana
          sayfadan birine geçebilir ya da üstteki arama kutusunu kullanabilirsiniz.
        </p>
      </div>
      <Link
        href="/"
        className="flex items-center gap-1.5 rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground transition-colors hover:bg-primary/90"
      >
        <Home className="size-4" />
        Kokpit&apos;e dön
      </Link>
    </div>
  );
}
