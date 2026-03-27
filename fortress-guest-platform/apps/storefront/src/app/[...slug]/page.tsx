import type { Metadata } from "next";

import {
  ArchivePageContent,
  generateArchiveMetadata,
} from "@/lib/archive-page";

type CatchAllParams = { slug: string[] };

export const revalidate = 0;

function normalizeJoinedSlug(parts: string[]): string {
  return parts
    .map((part) => part.trim())
    .filter(Boolean)
    .join("/");
}

export async function generateMetadata(
  { params }: { params: Promise<CatchAllParams> | CatchAllParams },
): Promise<Metadata> {
  const { slug } = await Promise.resolve(params);
  const joinedSlug = normalizeJoinedSlug(slug);
  const canonicalPath = `/${joinedSlug}`;

  return generateArchiveMetadata({
    slug: joinedSlug,
    canonicalPath,
  });
}

export default async function LegacyCatchAllPage(
  { params }: { params: Promise<CatchAllParams> | CatchAllParams },
) {
  const { slug } = await Promise.resolve(params);
  const joinedSlug = normalizeJoinedSlug(slug);
  const canonicalPath = `/${joinedSlug}`;

  return ArchivePageContent({
    slug: joinedSlug,
    canonicalPath,
    pathLabel: "Requested legacy path",
    pathValue: canonicalPath,
  });
}
