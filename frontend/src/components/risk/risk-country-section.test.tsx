import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { riskCountry, riskItem } from "@/lib/__fixtures__/risk";

import { CountrySection } from "./risk-country-section";

/** The whole point of the confidence work: a thinly-sourced signal is neither
 * hidden nor drawn as loudly as three agencies agreeing. These tests pin down
 * the "neither" -- present, counted, quiet, and behind a disclosure. */
describe("CountrySection low-confidence block", () => {
  const solid = riskItem({ id: "solid", headline: "Rodos'ta orman yangını", severity: "high" });
  const weak = riskItem({
    id: "weak",
    headline: "Girit'te yangın ihbarı",
    severity: "high",
    visibility: "low",
  });

  it("shows the confident signals and collapses the weak ones behind a count", async () => {
    render(
      <CountrySection
        group={riskCountry("Greece", [solid, weak])}
        windowDays={14}
        onSelect={vi.fn()}
      />,
    );

    expect(screen.getByText("Rodos'ta orman yangını")).toBeInTheDocument();
    // Closed by default: a single blog must not sit at the same weight as three
    // agencies on the same screen.
    expect(screen.queryByText("Girit'te yangın ihbarı")).not.toBeInTheDocument();

    const toggle = screen.getByRole("button", { name: /Düşük güvenli sinyaller \(1\)/ });
    expect(toggle).toHaveAttribute("aria-expanded", "false");

    await userEvent.click(toggle);
    expect(screen.getByText("Girit'te yangın ihbarı")).toBeInTheDocument();
    expect(toggle).toHaveAttribute("aria-expanded", "true");
  });

  it("keeps the weak signals inside the country's own count", () => {
    // They cleared the publish floor -- the server would not have sent them
    // otherwise. A country header claiming a number the reader cannot reach by
    // opening every block on the page is a number nobody can reconcile.
    render(
      <CountrySection
        group={riskCountry("Greece", [solid, weak])}
        windowDays={14}
        onSelect={vi.fn()}
      />,
    );
    expect(screen.getByText("2 sinyal")).toBeInTheDocument();
  });

  it("draws no disclosure at all when every signal is well sourced", () => {
    render(
      <CountrySection group={riskCountry("Greece", [solid])} windowDays={14} onSelect={vi.fn()} />,
    );
    expect(screen.queryByRole("button", { name: /Düşük güvenli sinyaller/ })).not.toBeInTheDocument();
  });
});

describe("CountrySection age tag", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-08-30T12:00:00Z"));
  });
  afterEach(() => {
    vi.useRealTimers();
  });

  const stale = riskItem({
    id: "stale",
    headline: "Ege'de fırtına",
    is_fresh: false,
    is_updated: false,
    published_at: "2026-08-05T12:00:00Z",
    last_reported_at: "2026-08-05T12:00:00Z",
  });

  it('tags coverage older than a week with a muted "ESKİ" in a wide window', () => {
    render(
      <CountrySection group={riskCountry("Greece", [stale])} windowDays={30} onSelect={vi.fn()} />,
    );
    // Deliberately about the coverage, never about the event -- there is no
    // lifecycle anywhere in this data.
    expect(screen.getByTitle(/olayın bittiği anlamına gelmez/)).toHaveTextContent("ESKİ");
  });

  it("draws nothing in the narrow windows, where it would fire on everything", () => {
    render(
      <CountrySection group={riskCountry("Greece", [stale])} windowDays={14} onSelect={vi.fn()} />,
    );
    expect(screen.queryByText("ESKİ")).not.toBeInTheDocument();
  });
});

describe("CountrySection headline language", () => {
  it("hangs the source-language original off a translated card headline", () => {
    render(
      <CountrySection
        group={riskCountry("Greece", [
          riskItem({
            id: "tr",
            headline: "Rodos'ta orman yangını: tahliye sürüyor",
            headline_original: "Wildfires force evacuation of Rhodes",
            is_translated: true,
          }),
        ])}
        windowDays={14}
        onSelect={vi.fn()}
      />,
    );

    expect(
      screen.getByRole("button", { name: "Rodos'ta orman yangını: tahliye sürüyor" }),
    ).toHaveAttribute("title", "Wildfires force evacuation of Rhodes");
    expect(screen.queryByText("otomatik çeviri yok")).not.toBeInTheDocument();
  });

  it("marks an untranslated card rather than letting English pass as Turkish", () => {
    render(
      <CountrySection
        group={riskCountry("Greece", [
          riskItem({ id: "en", headline: "Wildfires force evacuation of Rhodes" }),
        ])}
        windowDays={14}
        onSelect={vi.fn()}
      />,
    );
    expect(screen.getByText("otomatik çeviri yok")).toBeInTheDocument();
  });
});
