import { SearchClient } from "@/components/search-client";

export default async function SearchPage({
  searchParams,
}: {
  searchParams: Promise<{ q?: string }>;
}) {
  const { q } = await searchParams;

  return (
    <div className="flex flex-col gap-6">
      <div className="flex flex-col gap-1">
        <h1 className="text-2xl font-semibold tracking-tight">Search</h1>
        <p className="text-sm text-muted-foreground">
          Full-text search across every verified article.
        </p>
      </div>
      <SearchClient initialQuery={q ?? ""} />
    </div>
  );
}
