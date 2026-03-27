import type { Metadata } from "next";

import { SeoReviewDetail } from "../_components/seo-review-detail";

export const metadata: Metadata = {
  title: "SEO Review Detail | Fortress Prime",
  description:
    "Internal HITL review surface for approving, editing, or rejecting a pending SEO patch.",
};

export default async function SeoReviewDetailPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;

  return <SeoReviewDetail patchId={id} />;
}
