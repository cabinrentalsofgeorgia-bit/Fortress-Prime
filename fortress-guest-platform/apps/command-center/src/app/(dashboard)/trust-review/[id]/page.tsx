import type { Metadata } from "next";

import { TrustReviewDetail } from "../_components/trust-review-detail";

export const metadata: Metadata = {
  title: "Trust Review Detail | Fortress Prime",
  description:
    "Internal HITL override surface for approving, modifying, or blocking a Trust Swarm escalation.",
};

export default async function TrustReviewDetailPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;

  return <TrustReviewDetail escalationId={id} />;
}
