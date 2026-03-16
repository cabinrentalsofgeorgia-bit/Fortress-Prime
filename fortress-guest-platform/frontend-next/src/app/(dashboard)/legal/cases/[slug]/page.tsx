import { CaseDetailShell } from "./_components/case-detail-shell";

export default async function CaseDetailPage({
  params,
}: {
  params: Promise<{ slug: string }>;
}) {
  const { slug } = await params;
  return <CaseDetailShell slug={slug} />;
}
