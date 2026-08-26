"use client";

import { useEffect } from "react";

// Next.js requirement: unlike error.tsx (which renders inside the root
// layout), this one replaces it entirely -- it's the only boundary that can
// catch a crash in the layout itself, so it has to bring its own <html>/
// <body>. Deliberately plain: it cannot rely on globals.css tokens loading
// correctly, since a layout-level crash is exactly the case where that
// isn't a safe assumption.
export default function GlobalError({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  useEffect(() => {
    console.error(error);
  }, [error]);

  return (
    <html lang="tr">
      <body
        style={{
          margin: 0,
          minHeight: "100vh",
          display: "flex",
          flexDirection: "column",
          alignItems: "center",
          justifyContent: "center",
          gap: "1.25rem",
          fontFamily: "system-ui, sans-serif",
          background: "#0c1115",
          color: "#e5ebef",
          textAlign: "center",
          padding: "1.5rem",
        }}
      >
        <h1 style={{ fontSize: "1.5rem", fontWeight: 600, margin: 0 }}>
          Uygulama yüklenemedi
        </h1>
        <p style={{ maxWidth: "24rem", color: "#a1aeb7", margin: 0 }}>
          Beklenmeyen bir hata oluştu. Yeniden deneyin; devam ederse birkaç dakika sonra
          tekrar bakın.
        </p>
        <button
          type="button"
          onClick={reset}
          style={{
            padding: "0.5rem 1.25rem",
            borderRadius: "0.375rem",
            border: "none",
            background: "#e9a93c",
            color: "#0c1115",
            fontWeight: 500,
            cursor: "pointer",
          }}
        >
          Yeniden dene
        </button>
      </body>
    </html>
  );
}
