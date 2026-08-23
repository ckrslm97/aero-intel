import { redirect } from "next/navigation";

// Öneriler is a tab of İçgörüler now, not a page of its own. The route stays
// alive as a redirect so old links, bookmarks and anything already pointing
// here land on the tab instead of a 404.
export default function RecommendationsPage() {
  redirect("/insights?tab=oneriler");
}
