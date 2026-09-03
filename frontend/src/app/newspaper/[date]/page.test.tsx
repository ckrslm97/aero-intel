import { render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { EditionOut } from "@/lib/types";

import EditionPage from "./page";

/** Nothing is mocked between the page and `apiFetch`: the whole point of this
 * change is that the API's error CODE survives the trip from the response body
 * into the page's branch, so the test drives the real chain and fakes only the
 * network. */
function respond(status: number, body: unknown) {
  vi.stubGlobal(
    "fetch",
    vi.fn(() =>
      Promise.resolve({
        ok: status >= 200 && status < 300,
        status,
        json: () => Promise.resolve(body),
      } as Response),
    ),
  );
}

/** Next's `notFound()` throws a sentinel the framework catches. Here it only
 * has to be distinguishable from a rendered page. */
const NOT_FOUND_THROWN = new Error("NEXT_NOT_FOUND");
vi.mock("next/navigation", () => ({
  notFound: () => {
    throw NOT_FOUND_THROWN;
  },
}));

vi.mock("next/link", () => ({
  default: ({ href, children }: { href: string; children: React.ReactNode }) => (
    <a href={href}>{children}</a>
  ),
}));

vi.mock("@/components/article-card", () => ({
  ArticleCard: () => <div>makale</div>,
}));

const open = () => EditionPage({ params: Promise.resolve({ date: "2026-09-04" }) });

describe("EditionPage", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("says the paper is not assembled yet rather than claiming the route is wrong", async () => {
    // Reading no longer publishes (backend/app/api/v1/editions.py), and the
    // assembly job starts hours after its 03:00 UTC schedule -- so every
    // morning "Günün Gazetesi", which links to the current UTC date, lands on
    // a day with no row. Answering that with notFound() told the reader "Bu
    // rota bilinmiyor", which is false twice over: the route is right and the
    // paper is on its way.
    respond(404, { detail: { code: "not_prepared_yet", message: "..." } });

    render(await open());

    expect(
      screen.getByRole("heading", { name: "Bu günün baskısı henüz hazırlanmadı" }),
    ).toBeInTheDocument();
    // ...and a way onward, because the reader still wants news.
    expect(screen.getByRole("link", { name: "Gazete" })).toHaveAttribute(
      "href",
      "/newspaper",
    );
    expect(screen.getByRole("link", { name: "Arşiv" })).toHaveAttribute(
      "href",
      "/archive",
    );
  });

  it("still 404s a past day nobody built", async () => {
    // The other direction, and the reason the backend draws the distinction at
    // all: "henüz hazırlanmadı" about 2024 would be the same lie reversed.
    respond(404, { detail: { code: "not_found", message: "..." } });

    await expect(open()).rejects.toBe(NOT_FOUND_THROWN);
  });

  it("still 404s when the body carries no code", async () => {
    // A 404 from a proxy, or from any deployment older than the code above:
    // nothing claims the paper is coming, so nothing may promise it.
    respond(404, { detail: "Edition not found" });

    await expect(open()).rejects.toBe(NOT_FOUND_THROWN);
  });

  it("renders the edition when there is one", async () => {
    const edition: EditionOut = {
      id: "e1",
      edition_date: "2026-09-04",
      status: "published",
      headline: "Kapasite artışı",
      executive_summary: "Özet",
      sections: [],
      pdf_available: false,
    };
    respond(200, edition);

    render(await open());

    expect(screen.getByText("Kapasite artışı")).toBeInTheDocument();
  });
});
