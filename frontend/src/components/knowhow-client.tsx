"use client";

import { ArrowUpRight, Search } from "lucide-react";
import Link from "next/link";
import { useMemo, useState } from "react";

import { KNOW_HOW, type Term } from "@/lib/knowhow";
import { CATEGORY_BY_SLUG } from "@/lib/taxonomy";
import { cn } from "@/lib/utils";

/** Case- and diacritic-insensitive, because nobody types "ücret sınıfı" with
 * the right characters when they are searching for it in a hurry. */
function fold(value: string): string {
  return value
    .toLocaleLowerCase("tr")
    .normalize("NFD")
    .replace(/[̀-ͯ]/g, "")
    .replace(/ı/g, "i");
}

function matches(term: Term, needle: string): boolean {
  if (!needle) return true;
  const haystack = fold(`${term.tr} ${term.en} ${term.definition} ${term.matters}`);
  return haystack.includes(fold(needle));
}

function newsHref(term: Term): string {
  const params = new URLSearchParams({ category: term.category });
  if (term.subcategory) params.set("subcategory", term.subcategory);
  return `/newspaper?${params.toString()}`;
}

export function KnowHowClient() {
  const [query, setQuery] = useState("");

  const groups = useMemo(
    () =>
      KNOW_HOW.map((group) => ({
        ...group,
        terms: group.terms.filter((term) => matches(term, query)),
      })).filter((group) => group.terms.length > 0),
    [query],
  );

  const total = groups.reduce((sum, group) => sum + group.terms.length, 0);

  return (
    <div className="flex flex-col gap-6 p-4 md:p-6">
      <header className="flex flex-col gap-2">
        <h1 className="text-2xl font-semibold tracking-tight">Know How</h1>
        <p className="max-w-2xl text-sm text-muted-foreground">
          Bu portalın yazıldığı dil. Her terimin altında ne olduğu, neden önemli olduğu ve
          o konudaki haberlere giden bir bağlantı var — tanımı okuyun, sonra o terimi
          kullanan haberleri okuyun.
        </p>
      </header>

      <div className="relative max-w-md">
        <Search className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" />
        <input
          type="search"
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          placeholder="Terim ara — RASK, overbooking, slot…"
          aria-label="Terim ara"
          className="w-full rounded-lg border border-border bg-background py-2 pl-9 pr-3 text-sm outline-none focus-visible:ring-2 focus-visible:ring-ring"
        />
      </div>

      {total === 0 && (
        <p className="rounded-xl border border-border bg-card p-6 text-sm text-muted-foreground">
          &ldquo;{query}&rdquo; için bir terim yok. Eklenmesini istediğiniz bir kavram varsa
          söyleyin — bu sayfa elle yazılıyor, tahmin üretmiyor.
        </p>
      )}

      {groups.map((group) => (
        <section key={group.slug} className="flex flex-col gap-3">
          <div className="flex flex-col gap-1 border-b border-border pb-2">
            <h2 className="text-lg font-semibold">{group.title}</h2>
            <p className="max-w-2xl text-xs text-muted-foreground">{group.intro}</p>
          </div>

          <div className="grid gap-3 md:grid-cols-2">
            {group.terms.map((term) => {
              const category = CATEGORY_BY_SLUG[term.category];
              return (
                <article
                  key={term.en}
                  className="flex flex-col gap-2 rounded-xl border border-border bg-card p-4"
                >
                  <div className="flex flex-wrap items-baseline gap-x-2 gap-y-1">
                    <h3 className="text-sm font-semibold">{term.tr}</h3>
                    <span className="font-mono text-[11px] text-muted-foreground">
                      {term.en}
                    </span>
                  </div>

                  <p className="text-sm text-muted-foreground">{term.definition}</p>

                  <p className="text-sm">
                    <span className="font-medium">Neden önemli: </span>
                    <span className="text-muted-foreground">{term.matters}</span>
                  </p>

                  <Link
                    href={newsHref(term)}
                    className={cn(
                      "mt-auto flex w-fit items-center gap-1 rounded-full border border-border px-2.5 py-1",
                      "text-[11px] text-muted-foreground transition-colors hover:bg-accent hover:text-foreground",
                    )}
                  >
                    {category?.label ?? term.category} haberleri
                    <ArrowUpRight className="size-3" />
                  </Link>
                </article>
              );
            })}
          </div>
        </section>
      ))}
    </div>
  );
}
