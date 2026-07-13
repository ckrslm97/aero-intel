import { redirect } from "next/navigation";

export default function NewspaperIndexPage() {
  const today = new Date().toISOString().slice(0, 10);
  redirect(`/newspaper/${today}`);
}
