import type { Metadata } from "next";
import { DocPage } from "@/lib/docs";

export const metadata: Metadata = {
  title: "OpenReef Beta Privacy Notice",
  robots: { index: true, follow: false },
};

export default function PrivacyPage() {
  return <DocPage name="privacy-notice" />;
}
