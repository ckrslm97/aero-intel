import { BarChart3 } from "lucide-react";

import { ComingSoon } from "@/components/coming-soon";

export default function FinancePage() {
  return (
    <ComingSoon
      icon={BarChart3}
      title="Financial Intelligence"
      description="Airline revenues, margins, and market comparisons are coming once financial data adapters are connected."
    />
  );
}
