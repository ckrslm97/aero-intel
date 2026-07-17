import { Route } from "lucide-react";

import { ComingSoon } from "@/components/coming-soon";

export default function RoutesPage() {
  return (
    <ComingSoon
      icon={Route}
      title="Rota İstihbaratı"
      description="Etkileşimli haritayla yeni, iptal edilen ve sezonluk rota takibi yakında geliyor."
    />
  );
}
