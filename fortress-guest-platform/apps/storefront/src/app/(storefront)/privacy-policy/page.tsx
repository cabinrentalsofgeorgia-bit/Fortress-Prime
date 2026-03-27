import type { Metadata } from "next";
import { notFound } from "next/navigation";

import { PolicyLayout } from "@/components/storefront/policy-layout";
import { getPolicyPage } from "@/lib/policy-pages";

export const metadata: Metadata = {
  title: "Privacy Policy",
  description:
    "Read the Cabin Rentals of Georgia privacy policy covering information handling, cookies, security, and marketing opt-out requests.",
  alternates: {
    canonical: "/privacy-policy",
  },
};

export default async function PrivacyPolicyPage() {
  const page = await getPolicyPage("privacy-policy");

  if (!page || page.kind !== "document") {
    notFound();
  }

  return <PolicyLayout page={page} />;
}
