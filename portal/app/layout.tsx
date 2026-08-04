import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "OpenReef beta",
  description: "Beta feedback inbox and tester roster for OpenReef.",
  // Owner-only tool: keep it out of every index, permanently.
  robots: { index: false, follow: false },
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
