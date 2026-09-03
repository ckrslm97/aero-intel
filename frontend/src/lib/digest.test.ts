import { describe, expect, it } from "vitest";

import { digestParagraphs, digestSpans } from "@/lib/digest";

// The real shape, from production /api/v1/tk on 2026-09-03.
const BODY = `**Genel Bakış**
Toplam 337 yolcunun değerlendirmesine göre THY'nin ortalama puanı 6,3.

**Öne Çıkan Temalar**
İstanbul transfer deneyimi en çok anılan konu.`;

describe("digest markdown", () => {
  it("başlık ile cümleyi ayrı paragraflara böler", () => {
    const parts = digestParagraphs(BODY);
    expect(parts).toHaveLength(4);
    expect(parts[0]).toBe("**Genel Bakış**");
    expect(parts[1]).toContain("337 yolcunun");
  });

  it("kalın koşuyu işaretler ve yıldızları metinden atar", () => {
    expect(digestSpans("**Genel Bakış**")).toEqual([
      { text: "Genel Bakış", strong: true },
    ]);
    expect(digestSpans("başında **kalın** ortada")).toEqual([
      { text: "başında ", strong: false },
      { text: "kalın", strong: true },
      { text: " ortada", strong: false },
    ]);
  });

  it("işaretsiz metne dokunmaz", () => {
    // Modelin bugün üretmediği her şey olduğu gibi kalır: bir renderer icat
    // etmek, okumadığımız bir formatı tahmin etmek olurdu.
    expect(digestSpans("düz cümle, # başlık değil, - madde değil")).toEqual([
      { text: "düz cümle, # başlık değil, - madde değil", strong: false },
    ]);
    expect(digestParagraphs("tek paragraf")).toEqual(["tek paragraf"]);
  });

  it("tek yıldızı kalın saymaz", () => {
    expect(digestSpans("*tek* yıldız")).toEqual([
      { text: "*tek* yıldız", strong: false },
    ]);
  });
});
