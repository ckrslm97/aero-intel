import { afterEach, describe, expect, it, vi } from "vitest";

import { ApiError, apiFetch } from "./api";

/** A `fetch` that answers once with the given status and body. */
function respond(status: number, body: string, ok = false) {
  vi.stubGlobal(
    "fetch",
    vi.fn(() =>
      Promise.resolve({
        ok,
        status,
        json: () => Promise.resolve(JSON.parse(body)),
      } as Response),
    ),
  );
}

describe("apiFetch error bodies", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("carries detail.code off an error response", async () => {
    // The status alone cannot separate two different facts that share it: GET
    // /editions/{date} answers 404 both for "not assembled yet" and for "no
    // such paper". The code was parsed and thrown away here, so the newspaper
    // page could only render one message for both.
    respond(404, '{"detail":{"code":"not_prepared_yet","message":"..."}}');

    const err = await apiFetch("/editions/2026-09-04").catch((e: unknown) => e);

    expect(err).toBeInstanceOf(ApiError);
    expect((err as ApiError).status).toBe(404);
    expect((err as ApiError).code).toBe("not_prepared_yet");
  });

  it("reports no code when the body has none, rather than failing to parse", async () => {
    // An error response is exactly where the body may be a proxy's HTML, empty,
    // or JSON of another shape. Reading it must never replace the caller's real
    // HTTP error with a parse error.
    respond(500, "<html>502 Bad Gateway</html>");

    const err = await apiFetch("/editions/2026-09-04").catch((e: unknown) => e);

    expect(err).toBeInstanceOf(ApiError);
    expect((err as ApiError).status).toBe(500);
    expect((err as ApiError).code).toBeNull();
  });

  it("reports no code when detail is a plain string", async () => {
    // FastAPI's default shape. Not an error, just nothing to say.
    respond(404, '{"detail":"Edition not found"}');

    const err = await apiFetch("/editions/2026-09-04").catch((e: unknown) => e);

    expect((err as ApiError).code).toBeNull();
  });
});
