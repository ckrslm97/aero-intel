import type { Metadata } from "next";
import { Geist, Geist_Mono } from "next/font/google";

import { AppShell } from "@/components/layout/app-shell";
import { QueryProvider } from "@/components/query-provider";
import { ThemeProvider } from "@/components/theme-provider";
import "./globals.css";

const geistSans = Geist({
  variable: "--font-geist-sans",
  subsets: ["latin"],
});

const geistMono = Geist_Mono({
  variable: "--font-geist-mono",
  subsets: ["latin"],
});

export const metadata: Metadata = {
  title: {
    default: "AeroIntel — Havacılık İstihbarat Portalı",
    template: "%s · AeroIntel",
  },
  description:
    "Otomatik günlük havacılık istihbaratı: güvenilir kaynaklardan doğrulanmış haberler, KPI'lar ve piyasa verileri.",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html
      lang="tr"
      suppressHydrationWarning
      className={`${geistSans.variable} ${geistMono.variable} h-full antialiased`}
    >
      <head>
        {/* Carrier logos (see components/airline-logo.tsx) */}
        <link rel="preconnect" href="https://pics.avs.io" crossOrigin="" />
      </head>
      <body className="min-h-full flex flex-col">
        <ThemeProvider
          attribute="class"
          defaultTheme="dark"
          enableSystem
          disableTransitionOnChange
        >
          <QueryProvider>
            
              <AppShell>{children}</AppShell>
            
          </QueryProvider>
        </ThemeProvider>
      </body>
    </html>
  );
}
