import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { SignalsClient } from "./signals-client";
import type { SignalOut, SignalsOut } from "@/lib/types";

const apiFetch = vi.hoisted(() => vi.fn());
vi.mock("@/lib/api", () => ({ apiFetch, API_BASE_URL: "http://test/api/v1" }));

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

function payload(signals: SignalOut[]): SignalsOut {
  return {
    days: 30,
    total: signals.length,
    signals,
    streams: [
      {
        key: "risk",
        label_tr: "Risk Radarı",
        kind: "risk",
        count: signals.filter((s) => s.kind === "risk").length,
        available: signals.some((s) => s.kind === "risk"),
        empty_message: signals.some((s) => s.kind === "risk") ? null : "Bu akışta sinyal yok.",
      },
      {
        key: "network",
        label_tr: "Ağ sinyalleri",
        kind: "market",
        count: 0,
        available: false,
        empty_message: "Bu akışta sinyal yok.",
      },
    ],
    generated_at: "2026-08-31T12:00:00Z",
  };
}

describe("SignalsClient", () => {
  beforeEach(() => {
    apiFetch.mockReset();
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

  it("lists a stream that produced nothing instead of dropping it", async () => {
    // A reader has to be able to tell "nothing happened" from "it broke".
    apiFetch.mockResolvedValue(payload([signal({ id: "r1" })]));

    render(<SignalsClient />);

    expect(await screen.findByTitle("Bu akışta sinyal yok.")).toHaveTextContent(
      "Ağ sinyalleri",
    );
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
});
