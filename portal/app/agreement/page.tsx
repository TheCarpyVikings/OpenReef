import type { Metadata } from "next";
import { DocPage } from "@/lib/docs";

export const metadata: Metadata = {
  title: "OpenReef Beta Agreement",
  // Public on purpose (unlike the rest of the portal): testers accept this at
  // enrolment, so they must be able to read it without an account.
  robots: { index: true, follow: false },
};

export default function AgreementPage() {
  return <DocPage name="beta-agreement" />;
}
