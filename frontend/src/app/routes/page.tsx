import { Route } from "lucide-react";

import { ComingSoon } from "@/components/coming-soon";

export default function RoutesPage() {
  return (
    <ComingSoon
      icon={Route}
      title="Route Intelligence"
      description="New, cancelled, and seasonal route tracking with an interactive map is coming soon."
    />
  );
}
