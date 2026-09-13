import type { Metadata, Viewport } from "next";
import { GeistMono } from "geist/font/mono";
import { GeistSans } from "geist/font/sans";

import { THEME_SCRIPT } from "@/lib/theme";

import "./globals.css";

export const metadata: Metadata = {
  title: "MES Copilot — Smart CNC Factory",
  description:
    "Ask the factory a question. The agent plans the MES calls, the engine does the arithmetic, and every number on screen is traceable to a database row.",
};

export const viewport: Viewport = {
  themeColor: [
    { media: "(prefers-color-scheme: light)", color: "#f5f5f2" },
    { media: "(prefers-color-scheme: dark)", color: "#0a0b0d" },
  ],
};

// The font files ship inside the build. The page makes no request to a font
// server, which is the only way it can render correctly on an isolated network.
export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    // The theme attribute is set by the script below before React hydrates, so
    // the server's markup and the live <html> legitimately differ there.
    <html lang="en" className={`${GeistSans.variable} ${GeistMono.variable}`} suppressHydrationWarning>
      <head>
        <script dangerouslySetInnerHTML={{ __html: THEME_SCRIPT }} />
      </head>
      <body className="min-h-screen">{children}</body>
    </html>
  );
}
