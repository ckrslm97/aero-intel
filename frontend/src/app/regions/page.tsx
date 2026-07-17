import { Globe2 } from "lucide-react";

import { ComingSoon } from "@/components/coming-soon";
import { worldRegions } from "@/lib/nav";

export default function RegionsPage() {
  return (
    <div className="flex flex-col gap-8">
      <div className="flex flex-col gap-1">
        <h1 className="text-2xl font-semibold tracking-tight">
          Bölgesel İstihbarat
        </h1>
        <p className="text-sm text-muted-foreground">
          Dünya bölgesine göre haberler, istatistikler ve gelişmeler.
        </p>
      </div>
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-4">
        {worldRegions.map((region) => (
          <div
            key={region.slug}
            className="flex items-center gap-2 rounded-lg border border-border bg-card px-4 py-3 text-sm font-medium text-card-foreground/70"
          >
            <Globe2 className="size-4 text-muted-foreground" />
            {region.name}
          </div>
        ))}
      </div>
      <ComingSoon
        icon={Globe2}
        title="Bölge sayfaları hazırlanıyor"
        description="Ülke/şehir haberleri, havacılık istatistikleri ve havalimanı gelişmeleri içeren etkileşimli bölge kartları, veri toplama devreye girdiğinde eklenecek."
      />
    </div>
  );
}
