import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import {
  currentParams,
  resetNavigation,
  setUrl,
} from "@/lib/__fixtures__/next-navigation";
import { riskFunnel, riskQuality, riskRejection } from "@/lib/__fixtures__/risk";
import type { RiskRejection } from "@/lib/types";

import { RiskVerificationClient } from "./risk-verification-client";

const apiFetch = vi.hoisted(() => vi.fn());
vi.mock("@/lib/api", () => ({ apiFetch, API_BASE_URL: "http://test/api/v1" }));

// A real (fake) address bar: this screen reads ?days off it now, so the radar
// can hand it the window the reader was actually looking at.
vi.mock("next/navigation", async () => await import("@/lib/__fixtures__/next-navigation"));

const STAGES = riskFunnel([
  { key: "toplam", label: "Toplam makale", passed: 400 },
  { key: "risk_adayi", label: "Risk adayı", passed: 30, dropKind: null },
  { key: "pencere", label: "Pencere içinde (son 5 gün)", passed: 12, reason: "outside_window" },
  { key: "guncel", label: "Güncel olay", passed: 10, reason: "not_current_event" },
  { key: "havacilik", label: "Havacılık ilgisi", passed: 7, reason: "aviation_relevance_low" },
  { key: "kume", label: "Kümeleme sonrası sinyal", passed: 5, dropKind: "merged" },
]);

/** Every `/risks/rejected` path the component asked for, in order. The filter
 * is a server round trip, not a client-side narrowing, so the query string is
 * the only place its correctness is observable. */
const requested: string[] = [];

function serve(rows: RiskRejection[], overrides: Parameters<typeof riskQuality>[1] = {}) {
  apiFetch.mockImplementation((path: string) => {
    if (path.startsWith("/risks/quality")) {
      return Promise.resolve(riskQuality(STAGES, overrides));
    }
    if (path.startsWith("/risks/rejected")) {
      requested.push(path);
      const reason = new URL(path, "http://test").searchParams.get("reason");
      return Promise.resolve(reason ? rows.filter((r) => r.reason === reason) : rows);
    }
    return Promise.reject(new Error(`unexpected ${path}`));
  });
}

const stale = riskRejection({
  article_id: "stale",
  title: "Investigators provide update on anniversary of Southend Airport crash tragedy",
  reason: "not_current_event",
  reason_label_tr: "Güncel olay değil",
});
const irrelevant = riskRejection({
  article_id: "irrelevant",
  title: "Ukraine strikes Russian pipeline station",
  reason: "aviation_relevance_low",
  reason_label_tr: "Havacılıkla ilgisiz",
  aviation_relevance_score: 0.1,
});

describe("RiskVerificationClient", () => {
  beforeEach(() => {
    apiFetch.mockReset();
    requested.length = 0;
    resetNavigation("/risk-radari/dogrulama");
  });

  it("draws the funnel and the rejections together", async () => {
    serve([stale, irrelevant]);
    render(<RiskVerificationClient />);

    expect(await screen.findByText("Toplam makale")).toBeInTheDocument();
    expect(screen.getByText("400")).toBeInTheDocument();
    expect(
      await screen.findByText(
        "Investigators provide update on anniversary of Southend Airport crash tragedy",
      ),
    ).toBeInTheDocument();
  });

  it("filters the table by reason, on the server rather than in the browser", async () => {
    serve([stale, irrelevant]);
    render(<RiskVerificationClient />);

    await screen.findByText("Ukraine strikes Russian pipeline station");
    await userEvent.click(screen.getByRole("button", { name: /Havacılıkla ilgisiz/ }));

    await waitFor(() =>
      expect(
        screen.queryByText(
          "Investigators provide update on anniversary of Southend Airport crash tragedy",
        ),
      ).not.toBeInTheDocument(),
    );
    expect(screen.getByText("Ukraine strikes Russian pipeline station")).toBeInTheDocument();
    expect(requested.at(-1)).toContain("reason=aviation_relevance_low");
  });

  it("clicking a funnel stage's count filters the table below it", async () => {
    // The funnel and the table must describe the same set. Two independent
    // filters over one screen is two chances to disagree about what is being
    // looked at.
    serve([stale, irrelevant]);
    render(<RiskVerificationClient />);

    await screen.findByText("Ukraine strikes Russian pipeline station");
    await userEvent.click(
      screen.getByRole("button", { name: /3 elendi · aviation_relevance_low/ }),
    );

    await waitFor(() => expect(requested.at(-1)).toContain("reason=aviation_relevance_low"));
  });

  it("says the window is clean rather than rendering an empty table", async () => {
    serve([]);
    render(<RiskVerificationClient />);
    expect(
      await screen.findByText("Bu pencerede hiçbir risk adayı elenmedi."),
    ).toBeInTheDocument();
    expect(screen.queryByText("Başlık")).not.toBeInTheDocument();
  });

  it("says which reason came back empty when a filter is active", async () => {
    serve([irrelevant]);
    render(<RiskVerificationClient />);

    await screen.findByText("Ukraine strikes Russian pipeline station");
    await userEvent.click(screen.getByRole("button", { name: /Güncel olay değil/ }));
    expect(await screen.findByText("Bu sebeple elenen aday yok.")).toBeInTheDocument();
  });

  it("states how much of each gate is being carried by unmeasured rows", async () => {
    // The sentence the whole screen is built to make defensible: three gates
    // publish rows nobody measured, and a funnel that did not say so would read
    // as far stronger evidence than it is.
    serve([], { aviation_unscored: 6, location_unscored: 4, confidence_unscored: 2 });
    render(<RiskVerificationClient />);

    const note = await screen.findByText(/Kapılar ölçülmemiş satırları/);
    expect(within(note).getByText("6")).toBeInTheDocument();
    expect(within(note).getByText("4")).toBeInTheDocument();
    expect(within(note).getByText("2")).toBeInTheDocument();
  });

  it("keeps the funnel when the rejection list fails, and the other way round", async () => {
    // Faz 12's per-source contract: a source going down thins the page by one
    // section rather than blanking it.
    apiFetch.mockImplementation((path: string) => {
      if (path.startsWith("/risks/quality")) return Promise.resolve(riskQuality(STAGES));
      return Promise.reject(new Error("500"));
    });
    render(<RiskVerificationClient />);

    expect(await screen.findByText("Toplam makale")).toBeInTheDocument();
    expect(await screen.findByText("Veri geçici olarak kullanılamıyor.")).toBeInTheDocument();
  });

  it("refetches both sources when the window changes", async () => {
    serve([irrelevant]);
    render(<RiskVerificationClient />);

    await screen.findByText("Ukraine strikes Russian pipeline station");
    await userEvent.click(screen.getByRole("button", { name: "14g" }));

    await waitFor(() => expect(requested.at(-1)).toContain("days=14"));
    expect(apiFetch).toHaveBeenCalledWith(
      expect.stringContaining("/risks/quality?days=14"),
      expect.anything(),
    );
    // ...and the window is now in the address bar, so the way back to the
    // radar can restore it.
    expect(currentParams().get("days")).toBe("14");
  });

  it("audits the window the link names, not its own default", async () => {
    // THE POINT OF ?days ON THIS SCREEN. The radar's "Veri doğrulama" link
    // carries the window the reader was looking at; opening the funnel on its
    // own 5-day default would audit a different set of days than the one just
    // read -- two screens, two answers, under one question.
    setUrl("/risk-radari/dogrulama?days=30&country=Yunanistan");
    serve([irrelevant]);
    render(<RiskVerificationClient />);

    await screen.findByText("Ukraine strikes Russian pipeline station");
    expect(apiFetch).toHaveBeenCalledWith(
      expect.stringContaining("/risks/quality?days=30"),
      expect.anything(),
    );
    expect(requested.every((path) => path.includes("days=30"))).toBe(true);
    expect(screen.getByRole("button", { name: "30g" })).toHaveAttribute(
      "aria-pressed",
      "true",
    );

    // The country rides along so the way back restores the radar's own view,
    // and the screen says out loud that it is not applying it.
    expect(screen.getByRole("link", { name: /Risk Radarı/ })).toHaveAttribute(
      "href",
      "/risk-radari?days=30&country=Yunanistan",
    );
    expect(screen.getByText(/ülkeye göre daralmaz/)).toBeInTheDocument();
    // The negative half: the audit endpoints have no country filter, so the
    // name must never reach one. Asking for it would silently return the
    // unfiltered funnel under a heading that claims otherwise.
    expect(requested.some((path) => path.includes("country"))).toBe(false);
    expect(
      apiFetch.mock.calls.some((call) => String(call[0]).includes("country")),
    ).toBe(false);
  });

  it("drops a rejection reason the funnel does not publish", async () => {
    // A hand-edited ?reason= must not empty the table while "Tümü" is still
    // lit -- the same rule the campaign filters state for ?band=purple.
    setUrl("/risk-radari/dogrulama?reason=uydurma_sebep");
    serve([stale, irrelevant]);
    render(<RiskVerificationClient />);

    await screen.findByText("Ukraine strikes Russian pipeline station");
    await waitFor(() =>
      expect(requested.at(-1)).not.toContain("reason=uydurma_sebep"),
    );
    expect(screen.getByRole("button", { name: "Tümü" })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
    // ...and it leaves the address bar too. Dropped from the request but kept
    // in the URL, the link would go on claiming a filter the table was not
    // applying -- what archive-client calls "worse than no filter at all" --
    // and forwarding it would pass the claim on.
    await waitFor(() => expect(currentParams().has("reason")).toBe(false));
  });

  it("keeps a reason the funnel does publish in the URL", async () => {
    // The negative half: the cleanup above must fire only for a reason the
    // vocabulary disowns, never for a working shared link.
    setUrl("/risk-radari/dogrulama?reason=not_current_event");
    serve([stale, irrelevant]);
    render(<RiskVerificationClient />);

    await screen.findByText(/Southend Airport crash tragedy/);
    await waitFor(() =>
      expect(requested.at(-1)).toContain("reason=not_current_event"),
    );
    expect(currentParams().get("reason")).toBe("not_current_event");
  });
  // --- A FAILED REQUEST IS NOT AN ANSWER TO THE NEW QUESTION ---------------

  it("does not leave the previous reason's rows under the newly lit chip", async () => {
    serve([stale, irrelevant]);
    render(<RiskVerificationClient />);
    await screen.findByText(/Southend Airport crash tragedy/);

    // The funnel keeps answering; only the table's endpoint goes down, which
    // is the normal shape of this outage.
    apiFetch.mockImplementation((path: string) =>
      path.startsWith("/risks/quality")
        ? Promise.resolve(riskQuality(STAGES))
        : Promise.reject(new Error("okunamadı")),
    );
    await userEvent.click(screen.getByRole("button", { name: /Havacılıkla ilgisiz/ }));

    // "Okunamadı" with a retry. NOT the rows fetched for "Güncel olay değil",
    // which are a true list for a question the reader has stopped asking, and
    // NOT "bu sebeple elenen aday yok", which would report a measurement that
    // was never taken.
    expect(await screen.findByText("Veri geçici olarak kullanılamıyor.")).toBeInTheDocument();
    expect(screen.queryByText(/Southend Airport crash tragedy/)).not.toBeInTheDocument();
    expect(screen.queryByText(/elenen aday yok/)).not.toBeInTheDocument();
    // Nor a stale badge: there is no old reading of THIS filter to be stale.
    expect(screen.queryByText(/Güncellenemedi/)).not.toBeInTheDocument();
  });

  it("stamps a stale table with the table's own last success, not the funnel's", async () => {
    serve([stale, irrelevant]);
    render(<RiskVerificationClient />);
    await screen.findByText(/Southend Airport crash tragedy/);

    apiFetch.mockImplementation((path: string) =>
      path.startsWith("/risks/quality")
        ? Promise.resolve(riskQuality(STAGES))
        : Promise.reject(new Error("okunamadı")),
    );
    await userEvent.click(screen.getByRole("button", { name: "Yenile" }));

    // Same filter, so the rows on screen are still an answer -- they stay,
    // marked stale.
    expect(await screen.findByText(/Güncellenemedi/)).toBeInTheDocument();
    expect(screen.getByText(/Southend Airport crash tragedy/)).toBeInTheDocument();
    // But the funnel's 09:00 stamp (its `generated_at`, still refreshing fine)
    // is not what this source last succeeded at, and one banner carrying the
    // other endpoint's time is the wrong-window claim in miniature.
    expect(screen.queryByText(/son başarılı: 09:00 UTC/)).not.toBeInTheDocument();
  });
});
