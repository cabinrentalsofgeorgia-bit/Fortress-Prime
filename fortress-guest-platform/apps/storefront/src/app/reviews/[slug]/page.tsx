import type { Metadata } from "next";

import {
  ArchivePageContent,
  generateArchiveMetadata,
} from "@/lib/archive-page";

type PageParams = { slug: string };

export const revalidate = 0;

export async function generateMetadata(
  { params }: { params: Promise<PageParams> | PageParams },
): Promise<Metadata> {
  const { slug } = await Promise.resolve(params);
  return generateArchiveMetadata({
    slug,
    canonicalPath: `/reviews/${slug}`,
  });
}

export default async function ReviewPage(
  { params }: { params: Promise<PageParams> | PageParams },
) {
  const { slug } = await Promise.resolve(params);
  return ArchivePageContent({
    slug,
    canonicalPath: `/reviews/${slug}`,
    pathLabel: "Canonical review path",
    pathValue: `/reviews/${slug}`,
  });
}
