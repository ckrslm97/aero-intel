import { KpiDetailClient } from "@/components/kpi-detail-client";

export default async function KpiDetailPage({
  params,
}: {
  params: Promise<{ metric_key: string }>;
}) {
  const { metric_key } = await params;

  return <KpiDetailClient metricKey={metric_key} />;
}
