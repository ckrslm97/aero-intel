import { redirect } from "next/navigation";

// The standalone Takvim page folded into the Gazete (Etkinlik category's
// "Takvim" view) in round 6 -- keep the old URL working.
export default function EventsPage() {
  redirect("/newspaper");
}
