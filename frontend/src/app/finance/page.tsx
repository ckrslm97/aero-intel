import { BarChart3 } from "lucide-react";

import { ComingSoon } from "@/components/coming-soon";

export default function FinancePage() {
  return (
    <ComingSoon
      icon={BarChart3}
      title="Finansal İstihbarat"
      description="Havayolu gelirleri, marjlar ve piyasa karşılaştırmaları, finansal veri bağlantıları kurulduğunda eklenecek."
    />
  );
}
