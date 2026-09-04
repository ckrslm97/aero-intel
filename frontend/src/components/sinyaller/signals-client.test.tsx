import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { currentParams, resetNavigation, setUrl } from "@/lib/__fixtures__/next-navigation";
import type { SignalOut, SignalsOut } from "@/lib/types";

import { SignalsClient } from "./signals-client";

const apiFetch = vi.hoisted(() => vi.fn());
vi.mock("@/lib/api", () => ({ apiFetch, API_BASE_URL: "http://test/api/v1" }));

// A real (fake) address bar: replace() moves it and every useSearchParams
// reader re-renders, because this page's two chips now live in the URL.
vi.mock("next/navigation", async () => await import("@/lib/__fixtures__/next-navigation"));

vi.mock("next/link", () => ({
  default: ({ href, children }: { href: string; children: React.ReactNode }) => (
    <a href={href}>{children}</a>
  ),
}));

function signal(overrides: Partial<SignalOut> & Pick<SignalOut, "id">): SignalOut {
  return {
    stream: "test",
    kind: "risk",
    kind_label_tr: "Risk",
    type_label_tr: "Volkanik faaliyet",
    severity: "high",
    severity_label_tr: "Yüksek",
    severity_basis_tr: "Risk Radarı'nın kendi şiddet sınıflandırması.",
    title_tr: "Etna'da kül bulutu",
    detail_tr: null,
    region: null,
    airline_codes: [],
    detected_at: null,
    confidence_score: null,
    source_label: "Reuters",
    href: null,
    ...overrides,
  };
}

function payload(
  signals: SignalOut[],
  overrides: Partial<SignalsOut> = {},
): SignalsOut {
  return {
    days: 30,
    total: signals.length,
    signals,
    risk_truncated: false,
    risk_scanned_articles: 12,
    streams: [
      {
        key: "risk",
        label_tr: "Risk Radarı",
        kind: "risk",
        count: signals.filter((s) => s.kind === "risk").length,
        total: null,
        available: signals.some((s) => s.kind === "risk"),
        empty_message: signals.some((s) => s.kind === "risk") ? null : "Bu akışta sinyal yok.",
      },
      {
        key: "network",
        label_tr: "Ağ sinyalleri",
        kind: "market",
        count: 0,
        total: 0,
        available: false,
        empty_message: "Bu akışta sinyal yok.",
      },
    ],
    cockpit_tiles: [],
    generated_at: "2026-08-31T12:00:00Z",
    ...overrides,
  };
}

describe("SignalsClient", () => {
  beforeEach(() => {
    apiFetch.mockReset();
    resetNavigation("/sinyaller");
  });

  it("renders each signal's stream vocabulary rather than re-deriving it", async () => {
    apiFetch.mockResolvedValue(
      payload([
        signal({
          id: "risk:1",
          region: "europe",
          airline_codes: ["EK"],
          confidence_score: 0.61,
          detected_at: new Date(Date.now() - 2 * 3_600_000).toISOString(),
          href: "/risk-radari",
        }),
      ]),
    );

    render(<SignalsClient />);

    expect(await screen.findByText("Etna'da kül bulutu")).toBeInTheDocument();
    // "Yüksek" appears twice on purpose -- once as the card's pill, once as
    // the severity chip -- so this asserts the card's copy specifically.
    expect(screen.getByRole("article")).toHaveTextContent("Yüksek");
    expect(screen.getByText("Volkanik faaliyet")).toBeInTheDocument();
    // Region slugs are resolved through the app's own Turkish names.
    expect(screen.getByText("Avrupa")).toBeInTheDocument();
    expect(screen.getByText("EK")).toBeInTheDocument();
    expect(screen.getByText("Güven 0.61")).toBeInTheDocument();
    expect(screen.getByText("2 sa önce")).toBeInTheDocument();
    expect(screen.getByText("Kaynak: Reuters")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Detay/ })).toHaveAttribute(
      "href",
      "/risk-radari",
    );
  });

  it("shows an em dash rather than the render time for a rolling-window signal", async () => {
    apiFetch.mockResolvedValue(payload([signal({ id: "m:1", detected_at: null })]));

    render(<SignalsClient />);

    expect(await screen.findByText("Etna'da kül bulutu")).toBeInTheDocument();
    expect(screen.getByText("—")).toBeInTheDocument();
  });

  it("omits the confidence chip entirely when the stream carries none", async () => {
    apiFetch.mockResolvedValue(payload([signal({ id: "c:1", confidence_score: null })]));

    render(<SignalsClient />);

    await screen.findByText("Etna'da kül bulutu");
    expect(screen.queryByText(/Güven/)).not.toBeInTheDocument();
  });

  it("prints the severity basis, including a stream that has no severity", async () => {
    // A "Düşük" pill on a route announcement is not a judgement that the route
    // is unimportant -- this note is what says which it is.
    apiFetch.mockResolvedValue(
      payload([
        signal({
          id: "n:1",
          severity: "low",
          severity_label_tr: "Düşük",
          severity_basis_tr: "Bu akışta şiddet verisi yok.",
        }),
      ]),
    );

    render(<SignalsClient />);

    expect(await screen.findByTitle("Bu akışta şiddet verisi yok.")).toBeInTheDocument();
  });

  it("filters by kind and by severity, and can be cleared", async () => {
    const user = userEvent.setup();
    apiFetch.mockResolvedValue(
      payload([
        signal({ id: "r1", title_tr: "Risk sinyali" }),
        signal({
          id: "c1",
          kind: "competitor",
          kind_label_tr: "Rakip",
          severity: "low",
          severity_label_tr: "Düşük",
          title_tr: "Rakip sinyali",
        }),
      ]),
    );

    render(<SignalsClient />);
    await screen.findByText("Risk sinyali");
    expect(screen.getByText("Rakip sinyali")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: /Rakip/ }));
    expect(screen.queryByText("Risk sinyali")).not.toBeInTheDocument();
    expect(screen.getByText("Rakip sinyali")).toBeInTheDocument();

    // "Hepsi" on the kind row clears that axis and nothing else.
    await user.click(screen.getAllByRole("button", { name: "Hepsi" })[0]);
    expect(screen.getByText("Risk sinyali")).toBeInTheDocument();
  });

  it("opens on the filters the URL names", async () => {
    // The positive half of "a view is a link": someone pasted
    // /sinyaller?kind=competitor into a message and this is what the
    // recipient must see -- their page narrowed the same way, without
    // touching a chip.
    setUrl("/sinyaller?kind=competitor");
    apiFetch.mockResolvedValue(
      payload([
        signal({ id: "r1", title_tr: "Risk sinyali" }),
        signal({
          id: "c1",
          kind: "competitor",
          kind_label_tr: "Rakip",
          title_tr: "Rakip sinyali",
        }),
      ]),
    );

    render(<SignalsClient />);

    expect(await screen.findByText("Rakip sinyali")).toBeInTheDocument();
    expect(screen.queryByText("Risk sinyali")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Rakip/ })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
  });

  it("writes a pressed chip into the URL and takes it back out when cleared", async () => {
    const user = userEvent.setup();
    apiFetch.mockResolvedValue(
      payload([
        signal({ id: "r1", title_tr: "Risk sinyali" }),
        signal({
          id: "c1",
          kind: "competitor",
          kind_label_tr: "Rakip",
          title_tr: "Rakip sinyali",
        }),
      ]),
    );

    render(<SignalsClient />);
    await screen.findByText("Risk sinyali");
    // The negative half: an untouched page carries no filter keys at all, so
    // "unfiltered" is one URL rather than several spellings of it.
    expect(currentParams().has("kind")).toBe(false);

    await user.click(screen.getByRole("button", { name: /Rakip/ }));
    expect(currentParams().get("kind")).toBe("competitor");

    await user.click(screen.getAllByRole("button", { name: "Hepsi" })[0]);
    expect(currentParams().has("kind")).toBe(false);
  });

  it("ignores a severity the feed has no vocabulary for", async () => {
    // A hand-edited or stale ?severity= must not empty the list while the
    // chip row still reads "Hepsi" -- that looks exactly like a broken build.
    setUrl("/sinyaller?severity=pembe");
    apiFetch.mockResolvedValue(payload([signal({ id: "r1", title_tr: "Risk sinyali" })]));

    render(<SignalsClient />);

    expect(await screen.findByText("Risk sinyali")).toBeInTheDocument();
  });

  it("lists a stream that produced nothing, and says so in words rather than as a 0", async () => {
    // A reader has to be able to tell "nothing happened" from "it broke", and
    // that distinction has to be ON SCREEN. It used to live entirely in a
    // `title` attribute over a dim `0` -- invisible to anyone skimming and
    // unreachable on a touch device, so both states drew as the same digit.
    apiFetch.mockResolvedValue(payload([signal({ id: "r1" })]));

    render(<SignalsClient />);

    const chip = await screen.findByTitle("Bu akışta sinyal yok.");
    expect(chip).toHaveTextContent("sinyal yok");
    expect(chip.parentElement).toHaveTextContent("Ağ sinyalleri");
  });

  it("never calls a quiet stream unreadable", async () => {
    // THE NEGATIVE HALF, and this round's own sin mirrored. `available` is the
    // server's `bool(count)`, so labelling an empty stream "okunamadı" would
    // invent an outage out of a measurement -- exactly the trade this whole
    // party is about, made in the other direction.
    apiFetch.mockResolvedValue(payload([signal({ id: "r1" })]));

    render(<SignalsClient />);

    await screen.findByTitle("Bu akışta sinyal yok.");
    expect(screen.queryByText(/okunamadı/i)).toBeNull();
  });

  it("says so when every stream is quiet", async () => {
    apiFetch.mockResolvedValue(payload([]));

    render(<SignalsClient />);

    expect(
      await screen.findByText("Şu anda hiçbir akışta sinyal yok."),
    ).toBeInTheDocument();
  });

  it("surfaces a failed load rather than rendering an empty page", async () => {
    apiFetch.mockRejectedValue(new Error("boom"));

    render(<SignalsClient />);

    await waitFor(() => expect(apiFetch).toHaveBeenCalled());
    expect(await screen.findByRole("button", { name: /Yeniden dene/i })).toBeInTheDocument();
  });

  // --- the tally is not always a total -------------------------------------

  it("attributes the window to the streams it actually governs", async () => {
    // `days` is the news lookback for the EVENT-derived streams; the risk
    // rollup keeps its own 14-day window and the campaign inbox has none
    // (backend/app/api/v1/signals.py). "N sinyal · 30 gün" claimed one window
    // over all seven, which this page cannot reproduce anywhere else.
    apiFetch.mockResolvedValue(payload([signal({ id: "risk:1" })]));

    render(<SignalsClient />);

    expect(await screen.findByText(/olay akışları 30 gün/)).toBeInTheDocument();
  });

  it("says the risk counts are a floor when the rollup was capped", async () => {
    apiFetch.mockResolvedValue(
      payload([signal({ id: "risk:1" })], {
        risk_truncated: true,
        risk_scanned_articles: 400,
      }),
    );

    render(<SignalsClient />);

    const note = await screen.findByText(/Risk taraması/);
    expect(note).toHaveTextContent("en yeni 400 haberinde durdu");
    expect(note).toHaveTextContent("hepsi bu kadar değil");
  });

  it("stays quiet about the cap when the rollup read the whole window", async () => {
    // The negative half. A disclosure printed every day is furniture, and on
    // an ordinary feed these counts really are complete.
    apiFetch.mockResolvedValue(payload([signal({ id: "risk:1" })]));

    render(<SignalsClient />);

    await screen.findByText(/olay akışları 30 gün/);
    expect(screen.queryByText(/Risk taraması/)).not.toBeInTheDocument();
  });
});
