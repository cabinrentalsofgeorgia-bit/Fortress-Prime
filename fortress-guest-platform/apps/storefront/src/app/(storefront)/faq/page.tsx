import type { Metadata } from "next";
import { notFound } from "next/navigation";

import { PolicyLayout } from "@/components/storefront/policy-layout";
import { getPolicyPage } from "@/lib/policy-pages";

export const metadata: Metadata = {
  title: "FAQ",
  description:
    "Browse the Cabin Rentals of Georgia guest FAQ covering booking, cabin policies, amenities, travel details, and Blue Ridge local information.",
  alternates: {
    canonical: "/faq",
  },
};

export default async function FaqPage() {
  const page = await getPolicyPage("faq");

  if (!page || page.kind !== "faq") {
    notFound();
  }

  return <PolicyLayout page={page} />;
}
