import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { riskFunnel, riskQuality, riskRejection } from "@/lib/__fixtures__/risk";
import type { RiskRejection } from "@/lib/types";

import { RiskVerificationClient } from "./risk-verification-client";

const apiFetch = vi.hoisted(() => vi.fn());
vi.mock("@/lib/api", () => ({ apiFetch, API_BASE_URL: "http://test/api/v1" }));

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
  });
});
