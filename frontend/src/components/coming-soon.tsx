import { Construction, type LucideIcon } from "lucide-react";

export function ComingSoon({
  title,
  description,
  icon: Icon = Construction,
}: {
  title: string;
  description: string;
  icon?: LucideIcon;
}) {
  return (
    <div className="flex min-h-[60vh] flex-col items-center justify-center gap-3 rounded-xl border border-dashed border-border p-12 text-center">
      <Icon className="size-8 text-muted-foreground" />
      <h1 className="text-xl font-semibold tracking-tight">{title}</h1>
      <p className="max-w-md text-sm text-muted-foreground">{description}</p>
    </div>
  );
}
