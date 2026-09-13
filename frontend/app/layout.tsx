import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Smart CNC Factory MES Copilot",
  description:
    "Ask the factory a question. The agent plans the MES calls, the engine does the arithmetic, and every number on screen is traceable to a database row.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body className="min-h-screen">{children}</body>
    </html>
  );
}
