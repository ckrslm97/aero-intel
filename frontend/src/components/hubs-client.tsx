"use client";

import { motion } from "framer-motion";
import { ChevronDown, Map as MapIcon, Plane, Route } from "lucide-react";
import Link from "next/link";
import dynamic from "next/dynamic";
import { useCallback, useMemo, useState } from "react";

import { AirlineLogo } from "@/components/airline-logo";
import { ArticleCard } from "@/components/article-card";
import { DataSourceError, InlineSourceError } from "@/components/data-source-error";
import { HubNetworkSignals } from "@/components/hub-network-signals";
import { MotionItem, MotionList } from "@/components/motion/motion-list";
import { Collapse } from "@/components/ui/collapse";
import { FilterChip, FilterChipGroup, filterChipClass } from "@/components/ui/filter-chip";
import { Skeleton } from "@/components/ui/skeleton";
import { apiFetch } from "@/lib/api";

// echarts is only needed once the map actually renders -- Faz 14: this was
// the one heavy map/chart bundle in the app still loaded eagerly, the same
// pattern (see newspaper-browser.tsx's RegionMap) just not yet applied here.
const HubMap = dynamic(
  () => import("@/components/hub-map").then((m) => m.HubMap),
  { ssr: false, loading: () => <Skeleton className="h-[380px] w-full rounded-xl" /> },
);
import { useDataSource } from "@/hooks/use-data-source";
import { useUrlState } from "@/hooks/use-url-state";
import {
  DEFAULT_HUB,
  HUB_DAY_OPTIONS,
  hubViewStateToSearchParams,
  parseHubViewState,
  type HubDays,
  type HubView,
  type HubViewState,
} from "@/lib/hubs";
import { fadeUpItem } from "@/lib/motion";
import { worldRegions } from "@/lib/nav";
import { CATEGORY_BY_SLUG, categoryVar } from "@/lib/taxonomy";
import { CATEGORY_SLUGS } from "@/lib/taxonomy.gen";
import type {
  ArticleListOut,
  CountryOut,
  HubDetailOut,
  HubOverviewOut,
} from "@/lib/types";
import { cn } from "@/lib/utils";

const REGION_NAME: Record<string, string> = Object.fromEntries(
  worldRegions.map((r) => [r.slug, r.name]),
);

// How many carriers/categories the panel shows before "+N daha". Five keeps
// the sidebar scannable at a glance; the rest is one click away.
const PANEL_PREVIEW = 5;
// Above this the note plausibly overflows three clamped lines. A character
// count is imprecise by design -- measuring real overflow costs a layout pass
// per hub selection and buys nothing the reader can see.
const NOTE_CLAMP_THRESHOLD = 180;

export function HubsClient() {
  // The whole view is URL-owned: tab, window, hub, country and the topic chip.
  // All five change what is on screen, so all five have to survive a paste
  // into a message -- and İçgörüler now deep-links straight to
  // /hublar?view=network-signals, which only works because `view` lives here.
  // See lib/hubs.ts for the parse/serialise pair (modelled on
  // lib/campaigns.ts) and hooks/use-url-state.ts for the navigation.
  const { params, replaceParams } = useUrlState();
  const state = useMemo(() => parseHubViewState(params, CATEGORY_SLUGS), [params]);
  const { view, days, hub: selected, country, category: selectedCategory } = state;

  const setState = useCallback(
    (next: Partial<HubViewState>) => {
      replaceParams(hubViewStateToSearchParams({ ...state, ...next }, params));
    },
    [params, replaceParams, state],
  );

  const setView = useCallback((next: HubView) => setState({ view: next }), [setState]);
  const setDays = useCallback((next: HubDays) => setState({ days: next }), [setState]);
  const setCountry = useCallback(
    (next: string) => setState({ country: next }),
    [setState],
  );

  // FOUR SOURCES, FOUR CONTRACTS, EACH KEYED ON THE SELECTION IT ANSWERS.
  //
  // These were three hand-rolled effects writing into one shared `error`
  // string and four state slots that outlived the selection that filled them,
  // which produced all three of this page's failures at once: switching IST to
  // CDG left IST's panel and IST's story list under a CDG heading until the
  // new requests landed; a failed overview left `overview` null forever, so
  // the map skeleton shimmered with nothing on the way; and every failure was
  // a dead-end sentence with no retry, blaming the server in the one voice
  // available for all four sources.
  //
  // `useDataSource` blanks each source's data IN THE RENDER its deps change
  // (see the hook's `sameSelection`), so no heading can ever sit above another
  // selection's evidence, and every branch below has its own retry.
  //
  // Each fetcher is gated on the tab that draws it. Ağ Sinyalleri renders none
  // of this state and is a landing URL of its own -- İçgörüler links straight
  // to /hublar?view=network-signals -- so ungated, every reader following that
  // link paid for /hubs, /taxonomy/countries, /articles and /hubs/IST on first
  // paint and saw the results of none of them. Resolving `null` rather than
  // skipping the hook keeps the gate inside the source, where the deps that
  // re-open it are already listed.
  const overviewSource = useDataSource(
    useCallback(
      (signal: AbortSignal) =>
        view === "hubs"
          ? apiFetch<HubOverviewOut | null>(`/hubs?days=${days}`, {
              cache: "default",
              signal,
            })
          : Promise.resolve(null),
      [view, days],
    ),
    [view, days],
  );
  const overview = overviewSource.data;

  // Its own source, not half of a `Promise.all` with the overview: the country
  // select and the hub map answer different questions, and one of them going
  // down should cost its own control rather than the map as well.
  const countriesSource = useDataSource(
    useCallback(
      (signal: AbortSignal) =>
        view === "hubs"
          ? apiFetch<CountryOut[] | null>(`/taxonomy/countries?days=${days}`, {
              cache: "default",
              signal,
            })
          : Promise.resolve(null),
      [view, days],
    ),
    [view, days],
  );
  // Memoised so the `?? []` does not hand `countriesByRegion` a fresh array
  // identity on every render and re-group the whole list for nothing.
  const countries: CountryOut[] = useMemo(
    () => countriesSource.data ?? [],
    [countriesSource.data],
  );

  /** Does the overview list the hub the URL is asking for?
   *
   * `null` while the overview is still in flight -- neither known nor unknown
   * yet, and printing "böyle bir hub yok" over a pending request would accuse
   * a link that turns out to be fine. */
  const hubIsKnown =
    selected === null || overview === null
      ? null
      : overview.hubs.some((entry) => entry.code === selected);

  /** The hub the DETAIL panel asks about: only once the overview has confirmed
   * the code is one of ours. A hand-edited or stale `?hub=XYZ` would otherwise
   * 404 into the generic "Haberler yüklenemedi", which blames the server for a
   * bad link. Strict, because /hubs/{code} is the request that 404s. */
  const hubForDetail = hubIsKnown === true ? selected : null;

  /** The hub the STORY LIST narrows by. Optimistic, because `/articles` cannot
   * 404 on a bad airport code -- it just matches nothing -- and waiting for the
   * overview here would cost every ordinary page load a second, wasted
   * unfiltered request before the real one. Only a code the overview has
   * actively disowned is dropped. */
  const hubForArticles = hubIsKnown === false ? null : selected;

  // The story list. Its own source and its own request: it answers a question
  // (`airport` + `country` + `category`) that stays answerable even when the
  // hub panel has nothing to show, so it must not wait on the overview.
  const articlesSource = useDataSource(
    useCallback(
      (signal: AbortSignal) => {
        if (view !== "hubs") return Promise.resolve(null);
        // `query`, not `params` -- the hook's `params` is the address bar and
        // this is the request. They carry different things (the request has
        // `limit`, the URL has `view`) and one name for both is how they start
        // drifting.
        const query = new URLSearchParams({ limit: "12" });
        if (hubForArticles) query.set("airport", hubForArticles);
        if (country) query.set("country", country);
        if (selectedCategory) query.set("category", selectedCategory);
        return apiFetch<ArticleListOut | null>(`/articles?${query.toString()}`, {
          cache: "default",
          signal,
        });
      },
      [view, hubForArticles, country, selectedCategory],
    ),
    [view, hubForArticles, country, selectedCategory],
  );
  const articles = articlesSource.data;

  // The hub panel. Gated on the overview so an unrecognised `?hub=` never
  // becomes a request: waiting one hop costs a panel that fades in slightly
  // later, and buys a bad deep link an honest sentence instead of a server
  // error it did not cause. `hubForDetail === null` resolves without asking,
  // which is also how the panel is cleared when its subject is gone -- no
  // setState in an effect body for that any more.
  const detailSource = useDataSource(
    useCallback(
      (signal: AbortSignal) =>
        view === "hubs" && hubForDetail
          ? apiFetch<HubDetailOut | null>(`/hubs/${hubForDetail}?days=${days}`, {
              cache: "default",
              signal,
            })
          : Promise.resolve(null),
      [view, hubForDetail, days],
    ),
    [view, hubForDetail, days],
  );
  const detail = detailSource.data;

  /** Hub selection resets the category: the chips are that hub's own topic
   * mix, so carrying one into a newly-picked hub would silently over-filter
   * (or empty) its list. */
  const selectHub = useCallback(
    (code: string | null) => setState({ hub: code, category: null }),
    [setState],
  );

  const countriesByRegion = useMemo(() => {
    const groups = new Map<string, CountryOut[]>();
    for (const item of countries) {
      const key = item.region ?? "other";
      const bucket = groups.get(key);
      if (bucket) bucket.push(item);
      else groups.set(key, [item]);
    }
    return [...groups.entries()].sort(([a], [b]) =>
      (REGION_NAME[a] ?? "Diğer").localeCompare(REGION_NAME[b] ?? "Diğer", "tr"),
    );
  }, [countries]);

  return (
    <div className="flex flex-col gap-6 p-4 md:p-6">
      <header className="flex flex-col gap-1">
        <h1 className="text-2xl font-semibold tracking-tight">Hub</h1>
        <p className="max-w-2xl text-sm leading-relaxed text-muted-foreground">
          İzlenen aktarma merkezleri ve haber arşivinin onlar hakkında biriktirdikleri.
          Bir hub seçin ya da ülkeye göre daraltın.
        </p>
      </header>

      <div className="flex w-fit items-center gap-1 self-start rounded-lg border border-border p-0.5">
        {(
          [
            ["hubs", "Genel Bakış", MapIcon],
            ["network-signals", "Ağ Sinyalleri", Route],
          ] as const
        ).map(([value, label, Icon]) => (
          <button
            key={value}
            type="button"
            onClick={() => setView(value)}
            className={cn(
              "flex items-center gap-1.5 rounded-md px-3 py-1.5 text-xs font-medium transition-colors",
              view === value
                ? "bg-primary text-primary-foreground"
                : "text-muted-foreground hover:bg-accent",
            )}
          >
            <Icon className="size-3.5" />
            {label}
          </button>
        ))}
      </div>

      {view === "network-signals" ? (
        <HubNetworkSignals />
      ) : (
        <>
      {/* A deep link naming a hub we do not track. Said plainly and with a way
          out: the alternative is a page that looks filtered to something and
          shows nothing, with no clue that the link is the problem. */}
      {hubIsKnown === false && (
        <p className="flex flex-wrap items-center gap-2 rounded-lg border border-dashed border-border p-3 text-sm text-muted-foreground">
          <span>
            Bağlantıdaki <span className="font-mono font-medium">{selected}</span> izlenen
            hub&apos;lar arasında değil; hiçbir hub seçili değil.
          </span>
          {/* No `active`: this is a way out of a dead deep link, not a filter
              that can be on or off. */}
          <FilterChip onClick={() => selectHub(DEFAULT_HUB)}>
            {DEFAULT_HUB}&apos;a dön
          </FilterChip>
        </p>
      )}

      <div className="flex flex-wrap items-center gap-x-5 gap-y-3 rounded-xl border border-border bg-card p-5">
        <FilterChipGroup label="Dönem" className="gap-2">
          {HUB_DAY_OPTIONS.map((option) => (
            <FilterChip
              key={option}
              active={days === option}
              onClick={() => setDays(option)}
            >
              Son {option} gün
            </FilterChip>
          ))}
        </FilterChipGroup>

        <div className="flex items-center gap-2">
          <label
            htmlFor="hub-country"
            className="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground"
          >
            Ülke
          </label>
          {/* Only countries the archive can actually filter by are listed --
              the backend counts them rather than offering all 51 names. */}
          <select
            id="hub-country"
            value={country}
            onChange={(event) => setCountry(event.target.value)}
            className="rounded-lg border border-border bg-background px-2.5 py-1.5 text-xs"
          >
            <option value="">Tüm ülkeler</option>
            {countriesByRegion.map(([region, list]) => (
              <optgroup key={region} label={REGION_NAME[region] ?? "Diğer"}>
                {list.map((item) => (
                  <option key={item.name} value={item.name}>
                    {item.name} ({item.article_count})
                  </option>
                ))}
              </optgroup>
            ))}
          </select>
          {country && (
            <FilterChip
              onClick={() => setCountry("")}
              label="Ülke filtresini temizle"
            >
              Temizle
            </FilterChip>
          )}
          {/* An empty select is a control offering nothing, which reads as
              "the archive has no countries". It has to say which it is. */}
          {countriesSource.error && !countriesSource.data && (
            <InlineSourceError
              message="Ülke listesi okunamadı."
              onRetry={countriesSource.retry}
              pending={countriesSource.pending}
            />
          )}
        </div>
      </div>

      {/* The map's three branches. The middle one is new: a failed overview
          left this skeleton shimmering forever, because the only thing that
          ever replaced it was a successful response that was no longer
          coming. */}
      {overview ? (
        <div className="overflow-hidden rounded-xl shadow-elev-1">
          <HubMap
            hubs={overview.hubs}
            routes={overview.routes}
            selected={selected}
            onSelect={selectHub}
          />
        </div>
      ) : overviewSource.error ? (
        <DataSourceError
          onRetry={overviewSource.retry}
          lastUpdated={overviewSource.lastUpdated}
          pending={overviewSource.pending}
        />
      ) : (
        <Skeleton className="h-[380px] w-full rounded-xl" />
      )}

      <FilterChipGroup label="Hub">
        {overview?.hubs.map((hub) => (
          <FilterChip
            key={hub.code}
            active={selected === hub.code}
            onClick={() => selectHub(hub.code === selected ? null : hub.code)}
            className={cn(
              "gap-1.5",
              // A hub the archive has nothing on is dimmed rather than hidden:
              // "IST has 40 articles and BRU has none" is the answer to a
              // question a reader is actually asking.
              hub.article_count === 0 && selected !== hub.code && "opacity-60",
            )}
          >
            <span className="font-semibold">{hub.code}</span>
            <span className="opacity-70">{hub.article_count}</span>
          </FilterChip>
        ))}
      </FilterChipGroup>

      <div className="grid gap-6 lg:grid-cols-[minmax(0,20rem)_minmax(0,1fr)]">
        {/* Keyed on the hub code so switching hubs remounts the panel instead
            of silently swapping its text.
            The panel is the selected hub's evidence, and `detail` belongs to
            the selected hub by construction: the source blanks it in the
            render the selection changes, so IST's carriers can no longer sit
            under CDG's heading for the length of a round trip.
            NO `AnimatePresence`. It was here with `mode="wait"`, which holds
            the incoming panel back until the outgoing one reports that its
            exit animation finished -- and in this stack (framer-motion 12 +
            React 19) that report never arrives. Switching hubs a second time
            would have left the reader looking at the first hub's panel
            forever. See components/ui/drawer-shell.tsx. */}
        <div className="flex flex-col gap-2">
          {detail && (
            <HubDetailPanel
              key={detail.code}
              detail={detail}
              selectedCategory={selectedCategory}
              onToggleCategory={(slug) =>
                setState({ category: selectedCategory === slug ? null : slug })
              }
            />
          )}
          {hubForDetail && detailSource.error && !detail && (
            <InlineSourceError
              message={`${hubForDetail} ayrıntısı okunamadı.`}
              onRetry={detailSource.retry}
              pending={detailSource.pending}
            />
          )}
          {hubForDetail && !detail && !detailSource.error && (
            <Skeleton className="h-64 w-full rounded-xl" />
          )}
        </div>

        <section className="flex flex-col gap-3">
          <h2 className="flex items-center gap-2 text-sm font-semibold">
            <Plane className="size-4 text-muted-foreground" />
            {/* `hubForArticles`, not `selected`: an unrecognised ?hub= narrows
                nothing, so a heading naming it would label an unfiltered list. */}
            {hubForArticles ? `${hubForArticles} haberleri` : "Haberler"}
            {country && <span className="text-muted-foreground">· {country}</span>}
          </h2>

          {/* "Bu seçim için haber yok" is a statement about the archive, so it
              is reachable only from a request that answered THIS selection.
              The list used to keep the previous hub's stories while the new
              request was out, and to print the empty sentence when one
              failed. */}
          {articlesSource.error && !articles ? (
            <DataSourceError
              onRetry={articlesSource.retry}
              lastUpdated={articlesSource.lastUpdated}
              pending={articlesSource.pending}
            />
          ) : articles ? (
            articles.items.length > 0 ? (
              <MotionList className="divide-y divide-border rounded-xl border border-border bg-card">
                {articles.items.map((article) => (
                  <MotionItem key={article.id} variant="scalePop">
                    <ArticleCard article={article} />
                  </MotionItem>
                ))}
              </MotionList>
            ) : (
              <p className="rounded-xl border border-border bg-card p-6 text-sm text-muted-foreground">
                Bu seçim için haber yok. Arşiv bu hub ya da ülke hakkında henüz bir şey
                toplamamış — uydurma yerine boş gösteriyoruz.
              </p>
            )
          ) : (
            <Skeleton className="h-64 w-full rounded-xl" />
          )}
        </section>
      </div>
        </>
      )}
    </div>
  );
}

/** The hub sidebar. Everything long is capped and expandable: the panel used
 * to print a full paragraph plus every carrier and every category, which made
 * a 20rem column scroll for hubs like IST. */
function HubDetailPanel({
  detail,
  selectedCategory,
  onToggleCategory,
}: {
  detail: HubDetailOut;
  selectedCategory: string | null;
  onToggleCategory: (slug: string) => void;
}) {
  const [noteOpen, setNoteOpen] = useState(false);
  const [carriersOpen, setCarriersOpen] = useState(false);
  const [categoriesOpen, setCategoriesOpen] = useState(false);

  const noteIsLong = detail.note_tr.length > NOTE_CLAMP_THRESHOLD;

  const carriersSeen = [...detail.carriers_seen].sort(
    (a, b) => b.article_count - a.article_count,
  );
  const previewCarriers = carriersSeen.slice(0, PANEL_PREVIEW);
  const restCarriers = carriersSeen.slice(PANEL_PREVIEW);

  const categories = [...detail.categories].sort((a, b) => b.count - a.count);
  const previewCategories = categories.slice(0, PANEL_PREVIEW);
  const restCategories = categories.slice(PANEL_PREVIEW);

  return (
    <motion.aside
      // No `useReducedMotion()` branch -- `<MotionConfig reducedMotion="user">`
      // honours the preference once, app-wide. That hook answers false on the
      // server and true on a client that asked for stillness, so choosing a
      // variant SET with it leaves the server's `opacity: 0` in the DOM for
      // exactly the readers who asked for less motion (see lib/motion.ts).
      variants={fadeUpItem}
      initial="hidden"
      animate="show"
      style={{ "--glow-color": "var(--primary)" } as React.CSSProperties}
      /* border-gradient already layers --card-sheen as its first background
         layer, so it composes the sheen and the gradient frame in one
         background-image instead of the two fighting over the property. */
      className="border-gradient flex h-fit flex-col gap-5 rounded-xl p-5 shadow-elev-1"
    >
      <div className="flex items-start justify-between gap-2">
        <div className="flex flex-col gap-0.5">
          <h2 className="text-lg font-semibold leading-tight">{detail.name}</h2>
          <p className="text-xs text-muted-foreground">
            {detail.city} · {detail.country} · {REGION_NAME[detail.region] ?? detail.region}
          </p>
        </div>
        <span className="rounded-md bg-gradient-to-br from-primary/20 to-chart-4/25 px-2 py-1 font-mono text-xs font-semibold text-primary ring-1 ring-primary/20 dark:from-primary/30 dark:to-chart-4/35 dark:ring-primary/35">
          {detail.code}
        </span>
      </div>

      <div className="flex flex-col gap-1">
        <p
          className={cn(
            "text-sm leading-relaxed text-muted-foreground",
            noteIsLong && !noteOpen && "line-clamp-3",
          )}
        >
          {detail.note_tr}
        </p>
        {noteIsLong && (
          <button
            type="button"
            onClick={() => setNoteOpen((open) => !open)}
            className="w-fit text-xs font-medium text-primary hover:underline"
          >
            {noteOpen ? "gizle" : "devamını gör"}
          </button>
        )}
      </div>

      {detail.carriers.length > 0 && (
        <div className="flex flex-col gap-2">
          <PanelLabel>Üssü burada</PanelLabel>
          {/* Straight into Gazete, pre-filtered to that carrier -- the same
              deep-link mechanism knowhow-client.tsx uses for ?category=. */}
          <div className="flex flex-wrap gap-1.5">
            {detail.carriers.map((code) => (
              <Link
                key={code}
                href={`/newspaper?airline=${code}`}
                className="flex items-center gap-1.5 rounded-full border border-border px-2 py-1 text-xs transition-colors hover:border-primary/50 hover:text-primary"
              >
                <AirlineLogo code={code} className="size-3.5" />
                {code}
              </Link>
            ))}
          </div>
        </div>
      )}

      <div className="flex flex-col gap-2">
        <PanelLabel>Son {detail.days} günde adı geçen taşıyıcılar</PanelLabel>
        {carriersSeen.length > 0 ? (
          <>
            <div className="flex flex-col gap-1.5">
              {previewCarriers.map((carrier) => (
                <CarrierRow key={carrier.code} carrier={carrier} />
              ))}
            </div>
            <Collapse open={carriersOpen}>
              <div className="flex flex-col gap-1.5 pt-1.5">
                {restCarriers.map((carrier) => (
                  <CarrierRow key={carrier.code} carrier={carrier} />
                ))}
              </div>
            </Collapse>
            <MoreToggle
              open={carriersOpen}
              hidden={restCarriers.length}
              onToggle={() => setCarriersOpen((open) => !open)}
            />
          </>
        ) : (
          <p className="text-xs text-muted-foreground">
            Bu dönemde bu hub&apos;la birlikte anılan taşıyıcı yok.
          </p>
        )}
      </div>

      {categories.length > 0 && (
        <div className="flex flex-col gap-2">
          <PanelLabel>Konu dağılımı</PanelLabel>
          <div className="flex flex-wrap gap-1.5">
            {previewCategories.map((entry) => (
              <CategoryChip
                key={entry.slug}
                entry={entry}
                active={selectedCategory === entry.slug}
                onToggle={() => onToggleCategory(entry.slug)}
              />
            ))}
          </div>
          <Collapse open={categoriesOpen}>
            <div className="flex flex-wrap gap-1.5 pt-1.5">
              {restCategories.map((entry) => (
                <CategoryChip
                key={entry.slug}
                entry={entry}
                active={selectedCategory === entry.slug}
                onToggle={() => onToggleCategory(entry.slug)}
              />
              ))}
            </div>
          </Collapse>
          <MoreToggle
            open={categoriesOpen}
            hidden={restCategories.length}
            onToggle={() => setCategoriesOpen((open) => !open)}
          />
        </div>
      )}
    </motion.aside>
  );
}

function PanelLabel({ children }: { children: React.ReactNode }) {
  return (
    <span className="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">
      {children}
    </span>
  );
}

function CarrierRow({
  carrier,
}: {
  carrier: HubDetailOut["carriers_seen"][number];
}) {
  return (
    <Link
      href={`/newspaper?airline=${carrier.code}`}
      className="-mx-1 flex items-center gap-2 rounded-md px-1 text-xs transition-colors hover:bg-accent/40 hover:text-primary"
    >
      <AirlineLogo code={carrier.code} name={carrier.name} className="size-3.5" />
      <span className="flex-1 truncate">{carrier.name}</span>
      <span className="font-mono tabular-nums text-muted-foreground">
        {carrier.article_count}
      </span>
    </Link>
  );
}

/** A topic filter, not a label: clicking narrows this hub's story list, and
 * clicking the active one clears it. The selected chip burns in its own
 * category hue -- the same lit-chip idiom as Gazete/Öneriler, inline because
 * the slug -> token transform is invisible to Tailwind's scanner, and composed
 * off `filterChipClass` for the same reason filters/category-chip-row.tsx is:
 * the hue is this chip's own business, the 24px measure and the focus ring are
 * not. It was left at `px-2 py-0.5 text-[11px]` -- an 18px target with no
 * focus ring -- while the two filter rows above it on the same card moved. */
function CategoryChip({
  entry,
  active,
  onToggle,
}: {
  entry: HubDetailOut["categories"][number];
  active: boolean;
  onToggle: () => void;
}) {
  const hue = categoryVar(entry.slug);
  return (
    <button
      type="button"
      onClick={onToggle}
      aria-pressed={active}
      style={
        active
          ? ({
              "--glow-color": hue,
              color: hue,
              backgroundColor: `color-mix(in srgb, ${hue} 14%, transparent)`,
            } as React.CSSProperties)
          : undefined
      }
      className={filterChipClass(
        active,
        active && "border-0 bg-transparent font-medium ring-1 ring-current/40 dark:glow-soft",
      )}
    >
      {CATEGORY_BY_SLUG[entry.slug]?.label ?? entry.slug} · {entry.count}
    </button>
  );
}

function MoreToggle({
  open,
  hidden,
  onToggle,
}: {
  open: boolean;
  hidden: number;
  onToggle: () => void;
}) {
  // Nothing to reveal and nothing revealed -- render no control at all.
  if (hidden <= 0) return null;
  return (
    <button
      type="button"
      onClick={onToggle}
      className="flex w-fit items-center gap-1 text-xs font-medium text-primary hover:underline"
    >
      <ChevronDown
        className={cn("size-3.5 transition-transform motion-reduce:transition-none", open && "rotate-180")}
      />
      {open ? "daha az göster" : `+${hidden} daha`}
    </button>
  );
}
