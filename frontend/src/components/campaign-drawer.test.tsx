import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { promotion } from "@/lib/__fixtures__/promotion";
import type { PromotionOut } from "@/lib/types";

import { CampaignDrawer } from "./campaign-drawer";

const apiFetch = vi.hoisted(() => vi.fn());
vi.mock("@/lib/api", () => ({ apiFetch, API_BASE_URL: "http://test/api/v1" }));

beforeEach(() => {
  apiFetch.mockReset();
  // The drawer loads its version/source history on mount; none of these tests
  // are about that panel, so both endpoints answer empty.
  apiFetch.mockResolvedValue([]);
});

function open(overrides: Partial<PromotionOut> = {}) {
  render(
    <CampaignDrawer
      promotion={promotion(overrides)}
      brandHex="#c1121f"
      onClose={vi.fn()}
    />,
  );
}

function cellDd(label: string): HTMLElement {
  const dt = screen.getByText(label);
  const value = dt.parentElement?.querySelector("dd");
  if (!value) throw new Error(`no value rendered for "${label}"`);
  return value as HTMLElement;
}

/** The cell's printed value, found through its label. */
function cellValue(label: string): string {
  return cellDd(label).textContent ?? "";
}

/** The cell's hover hint -- rendered as the value's `title`, not as text. */
function cellHint(label: string): string {
  return cellDd(label).getAttribute("title") ?? "";
}

/** THREE TIME CLAIMS, EACH NAMING A DIFFERENT REAL TIME.
 *
 * "Son kontrol" is when we last re-checked the campaign's own page, "İlk
 * tespit" is when we first saw the campaign, and the source article's
 * publication date is when the reporter filed. They used to be one column
 * wearing three hats, and the drawer papered over the gaps by falling back
 * from one to the next -- so a row that had never been re-checked printed its
 * first sighting under "Son kontrol", which is an answer to a question nobody
 * asked. The fallbacks are gone; what is pinned here is that they stay gone.
 */
describe("CampaignDrawer: her zaman hücresi kendi zamanını söyler", () => {
  it("prints last_seen_at as the last check, and not the other two stamps", () => {
    open({
      last_seen_at: "2026-08-25T14:30:00Z",
      last_changed_at: "2026-08-22T08:00:00Z",
      detected_at: "2026-08-20T09:00:00Z",
    });

    expect(cellValue("Son kontrol")).toBe("25 Ağu 2026 14:30 UTC");
    // The two stamps it used to fall back to are not in this cell.
    expect(cellValue("Son kontrol")).not.toContain("22 Ağu");
    expect(cellValue("Son kontrol")).not.toContain("20 Ağu");
  });

  it("says '—' when nothing has re-checked the row, rather than reusing the sighting", () => {
    // The news path (backend/app/pipeline/promotions.py) never writes
    // `last_seen_at`, so this is the shape of every campaign that reached us
    // through an article -- and "we last checked when we first saw it" would
    // be false for all of them.
    open({ last_seen_at: null, detected_at: "2026-08-20T09:00:00Z" });

    expect(cellValue("Son kontrol")).toBe("—");
    expect(cellValue("Son kontrol")).not.toContain("20 Ağu");
    expect(cellValue("İlk tespit")).toBe("20 Ağu 2026 09:00 UTC");
  });

  it("offers the reporter's date beside the sighting when the source carried one", () => {
    open({
      detected_at: "2026-08-20T09:00:00Z",
      source_published_at: "2026-07-04T09:30:00Z",
    });

    expect(cellHint("İlk tespit")).toContain(
      "Kaynak haberin yayın tarihi: 4 Tem 2026 09:30 UTC",
    );
  });

  it("says nothing about a publication date the source never stated", () => {
    // NULL means "the source stated no date", never "the day we saw it" --
    // the split this column exists for (backend/app/models/promotion.py).
    open({ detected_at: "2026-08-20T09:00:00Z", source_published_at: null });

    expect(cellHint("İlk tespit")).toBe("Kampanyayı ilk gördüğümüz an");
    expect(cellHint("İlk tespit")).not.toContain("yayın tarihi");
  });
});

/** A record's timestamp must not shift with who is reading it.
 *
 * `detected_at` and `last_seen_at` are full UTC datetimes. Formatted in the
 * reader's own zone, 2026-08-20T22:00Z is the 20th in London and the 21st in
 * Istanbul -- one row, two days, no way for two analysts to tell they are
 * looking at the same fact.
 *
 * The runner's TZ is pinned to Europe/Istanbul (package.json's `test` script,
 * and see vitest.config.ts for why): UTC+3 is what gives this assertion teeth.
 * A formatter that slipped back to the reader's zone would print "21 Ağu 2026
 * 01:00" for the instant below, on a different DAY from the one recorded.
 */
describe("CampaignDrawer: damgalar okuyucunun saat dilimine göre kaymaz", () => {
  it("keeps a late-evening UTC stamp on its own UTC day", () => {
    open({ last_seen_at: "2026-08-20T22:00:00Z", detected_at: "2026-08-20T22:00:00Z" });

    expect(cellValue("Son kontrol")).toBe("20 Ağu 2026 22:00 UTC");
    expect(cellValue("İlk tespit")).toBe("20 Ağu 2026 22:00 UTC");
  });
});
