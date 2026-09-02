import { render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { firstSentences, TodayIntelligence } from "./today-intelligence";

const apiFetch = vi.hoisted(() => vi.fn());
vi.mock("@/lib/api", () => ({ apiFetch, API_BASE_URL: "http://test/api/v1" }));

const insights = (digest: { date: string; body: string; provider: string } | null) => ({
  airline_momentum: [],
  new_route_signals: [],
  sentiment_by_category: [],
  digest,
});

describe("firstSentences", () => {
  it("keeps the first three and drops the rest", () => {
    expect(firstSentences("Bir. İki. Üç. Dört. Beş.")).toBe("Bir. İki. Üç.");
  });

  it("does not split a decimal or an ordinal", () => {
    // "10 üzerinden 5.7" is one sentence, not two -- a period is only a full
    // stop when whitespace or the end of the text follows it.
    expect(firstSentences("Ortalama 5.7 puan. Sonraki cümle. Üçüncü. Dördüncü.")).toBe(
      "Ortalama 5.7 puan. Sonraki cümle. Üçüncü.",
    );
  });

  it("keeps a trailing fragment that never terminates", () => {
    // A generator that stops without punctuation still said something.
    expect(firstSentences("Bir. İki cümlelik bir kuyruk")).toBe("Bir. İki cümlelik bir kuyruk");
  });

  it("returns a single unterminated sentence unchanged", () => {
    expect(firstSentences("Tek bir cümle")).toBe("Tek bir cümle");
  });
});

describe("TodayIntelligence", () => {
  beforeEach(() => {
    apiFetch.mockReset();
    // A resolved default, then each test says what it wants. Reset alone
    // leaves the mock returning `undefined`, and a rejection registered onto
    // that bare mock is reported by the runner as an unhandled rejection even
    // though the component does catch it -- the same convention every other
    // apiFetch-mocking test in this repo already follows.
    apiFetch.mockResolvedValue(insights(null));
  });

  it("renders NOTHING when the database has no daily digest", async () => {
    // The digest row is written by a scheduled job; a fresh database, a local
    // checkout or a morning before the job has run all legitimately have none.
    // A framed "özet bulunamadı" box would put an error where the paper's
    // first sentence belongs, on a page that is working perfectly.
    apiFetch.mockResolvedValue(insights(null));
    const { container } = render(<TodayIntelligence />);

    await waitFor(() => expect(apiFetch).toHaveBeenCalled());
    expect(container).toBeEmptyDOMElement();
  });

  it("renders nothing when the request fails", async () => {
    apiFetch.mockRejectedValue(new Error("boom"));
    const { container } = render(<TodayIntelligence />);

    await waitFor(() => expect(apiFetch).toHaveBeenCalled());
    expect(container).toBeEmptyDOMElement();
  });

  it("renders nothing for a digest row whose body is blank", async () => {
    apiFetch.mockResolvedValue(
      insights({ date: "2026-08-30", body: "   ", provider: "heuristic" }),
    );
    const { container } = render(<TodayIntelligence />);

    await waitFor(() => expect(apiFetch).toHaveBeenCalled());
    expect(container).toBeEmptyDOMElement();
  });

  it("prints three sentences and names the generator", async () => {
    apiFetch.mockResolvedValue(
      insights({
        date: "2026-08-30",
        body: "Bir. İki. Üç. Dört.",
        provider: "openai_compat",
      }),
    );
    render(<TodayIntelligence />);

    expect(await screen.findByText("Bir. İki. Üç.")).toBeInTheDocument();
    expect(screen.getByText("Yapay zekâ özeti")).toBeInTheDocument();
  });

  it("does not call the deterministic fallback a model's work", async () => {
    // "heuristic" is the template-shaped summary the backend writes when no
    // LLM is configured. Labelling it as AI would be a false claim about
    // provenance in the direction that flatters the product.
    apiFetch.mockResolvedValue(
      insights({ date: "2026-08-30", body: "Bir cümle.", provider: "heuristic" }),
    );
    render(<TodayIntelligence />);

    expect(await screen.findByText("Kural tabanlı özet")).toBeInTheDocument();
    expect(screen.queryByText("Yapay zekâ özeti")).not.toBeInTheDocument();
  });
});
