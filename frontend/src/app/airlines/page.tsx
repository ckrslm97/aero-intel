import { Plane } from "lucide-react";

import { ComingSoon } from "@/components/coming-soon";
import { airlineTabs } from "@/lib/nav";

export default function AirlinesPage() {
  return (
    <div className="flex flex-col gap-8">
      <div className="flex flex-col gap-1">
        <h1 className="text-2xl font-semibold tracking-tight">
          Havayolu İstihbaratı
        </h1>
        <p className="text-sm text-muted-foreground">
          Havayoluna göre filo, finansal ve ağ güncellemeleri.
        </p>
      </div>
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-5">
        {airlineTabs.map((airline) => (
          <div
            key={airline.code}
            className="flex flex-col gap-2 rounded-lg border border-border bg-card px-4 py-3"
          >
            <span
              className="flex size-8 items-center justify-center rounded-md text-xs font-bold text-white"
              style={{ backgroundColor: airline.color }}
            >
              {airline.code}
            </span>
            <span className="text-sm font-medium text-card-foreground/80">
              {airline.name}
            </span>
          </div>
        ))}
      </div>
      <ComingSoon
        icon={Plane}
        title="Havayolu sayfaları hazırlanıyor"
        description="Filo, finansal veriler ve rota haberleri içeren marka temalı havayolu sayfaları, haber toplama devreye girdiğinde eklenecek."
      />
    </div>
  );
}
