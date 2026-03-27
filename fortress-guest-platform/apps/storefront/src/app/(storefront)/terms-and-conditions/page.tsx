import type { Metadata } from "next";
import { notFound } from "next/navigation";

import { PolicyLayout } from "@/components/storefront/policy-layout";
import { getPolicyPage } from "@/lib/policy-pages";

export const metadata: Metadata = {
  title: "Terms and Conditions",
  description:
    "Review the Cabin Rentals of Georgia SMS terms and conditions for promotional and reservation-related messages.",
  alternates: {
    canonical: "/terms-and-conditions",
  },
};

export default async function TermsAndConditionsPage() {
  const page = await getPolicyPage("terms-and-conditions");

  if (!page || page.kind !== "document") {
    notFound();
  }

  return <PolicyLayout page={page} />;
}
