import type { Metadata } from "next";
import { DocPage } from "@/lib/docs";

export const metadata: Metadata = {
  title: "Welcome to the OpenReef beta",
  robots: { index: false, follow: false },
};

export default function WelcomePage() {
  return <DocPage name="welcome" />;
}
