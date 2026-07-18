import { AlertTriangle, BadgeCheck, HelpCircle, Landmark } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";
import type { VerificationStatus } from "@/lib/types";

/** How each stored verification_status is shown to the user. The whole point of
 * the /invest module: unverified data is labeled unverified, never dressed up. */
const CONFIG: Record<
  VerificationStatus,
  { label: string; icon: typeof BadgeCheck; className: string }
> = {
  verified: {
    label: "İki kaynaktan doğrulandı",
    icon: BadgeCheck,
    className: "bg-good/10 text-good border-good/30",
  },
  official_single_source: {
    label: "Resmî kaynak (TEFAS)",
    icon: Landmark,
    className: "bg-primary/10 text-primary border-primary/30",
  },
  single_source: {
    label: "Tek kaynak — doğrulanamadı",
    icon: HelpCircle,
    className: "bg-warning/10 text-warning border-warning/30",
  },
  discrepancy: {
    label: "Kaynaklar arasında fark var",
    icon: AlertTriangle,
    className: "bg-critical/10 text-critical border-critical/30",
  },
};

const STALE_AFTER_DAYS = 4;

function isStale(asOf: string | null | undefined): boolean {
  if (!asOf) return false;
  const ageDays = (Date.now() - new Date(asOf).getTime()) / 86_400_000;
  return ageDays > STALE_AFTER_DAYS;
}

export function VerificationBadge({
  status,
  asOf,
  className,
}: {
  status: VerificationStatus | null;
  asOf?: string | null;
  className?: string;
}) {
  if (!status) {
    return (
      <Badge variant="outline" className={cn("text-muted-foreground", className)}>
        Henüz veri yok
      </Badge>
    );
  }

  const { label, icon: Icon, className: statusClass } = CONFIG[status];
  const stale = isStale(asOf);

  return (
    <Badge variant="outline" className={cn("gap-1 border", statusClass, className)}>
      <Icon className="size-3" />
      {label}
      {stale && <span className="opacity-80">· güncel değil</span>}
    </Badge>
  );
}
