import { Bot, FileText, Info } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";
import type { FundAnalysisOut, FundOutlook } from "@/lib/types";

const OUTLOOK_CONFIG: Record<FundOutlook, { label: string; className: string }> = {
  positive: { label: "Olumlu görünüm", className: "bg-good/10 text-good border-good/30" },
  neutral: { label: "Nötr görünüm", className: "bg-muted text-muted-foreground border-border" },
  cautious: { label: "Temkinli görünüm", className: "bg-warning/10 text-warning border-warning/30" },
};

/** provider is stored on the row; the UI must say which pipeline wrote the text
 * so a deterministic template is never read as AI analysis. */
function providerLabel(provider: string): { label: string; icon: typeof Bot } {
  if (provider === "openai_compat") return { label: "Yapay zekâ analizi", icon: Bot };
  return { label: "Verilerden üretilen şablon", icon: FileText };
}

export function AnalysisPanel({
  analysis,
  title = "Analiz",
}: {
  analysis: FundAnalysisOut | null;
  title?: string;
}) {
  if (!analysis) {
    return (
      <div className="flex flex-col gap-2 rounded-xl border border-dashed border-border bg-card p-5">
        <h2 className="text-sm font-semibold uppercase tracking-wide text-muted-foreground">
          {title}
        </h2>
        <p className="text-sm text-muted-foreground">
          Analiz ilk veri güncellemesinden sonra oluşturulacak.
        </p>
      </div>
    );
  }

  const outlook = OUTLOOK_CONFIG[analysis.outlook];
  const { label: provLabel, icon: ProvIcon } = providerLabel(analysis.provider);
  const paragraphs = analysis.body_tr.split(/\n\s*\n/).filter((p) => p.trim());

  return (
    <div className="flex flex-col gap-4 rounded-xl border border-border bg-card p-5">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 className="text-sm font-semibold uppercase tracking-wide text-muted-foreground">
          {title}
        </h2>
        <div className="flex items-center gap-2">
          <Badge variant="outline" className={cn("gap-1 border", outlook.className)}>
            {outlook.label}
          </Badge>
          <Badge variant="outline" className="gap-1 text-muted-foreground">
            <ProvIcon className="size-3" />
            {provLabel}
          </Badge>
        </div>
      </div>

      <div className="flex flex-col gap-3 text-sm leading-relaxed text-foreground">
        {paragraphs.map((p, i) => (
          <p key={i}>{p}</p>
        ))}
      </div>

      <p className="text-xs text-muted-foreground">
        {new Date(analysis.analysis_date).toLocaleDateString("tr-TR", { dateStyle: "long" })}{" "}
        tarihli değerlendirme
      </p>

      <div className="flex items-start gap-2 rounded-lg border border-warning/30 bg-warning/5 p-3 text-xs text-muted-foreground">
        <Info className="mt-0.5 size-3.5 shrink-0 text-warning" />
        <span>{analysis.disclaimer}</span>
      </div>
    </div>
  );
}
