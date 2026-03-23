import { revalidatePath, revalidateTag } from "next/cache";
import { NextRequest, NextResponse } from "next/server";

const REVALIDATION_SECRET = process.env.EDGE_REVALIDATION_SECRET ?? "";

function hasValidBearerToken(authHeader: string | null): boolean {
  if (!REVALIDATION_SECRET) {
    return false;
  }

  const expected = `Bearer ${REVALIDATION_SECRET}`;
  return authHeader === expected;
}

function collectUniqueStrings(values: unknown): string[] {
  if (!Array.isArray(values)) {
    return [];
  }

  const normalized = values
    .map((value) => (typeof value === "string" ? value.trim() : ""))
    .filter(Boolean);

  return [...new Set(normalized)];
}

export async function POST(request: NextRequest) {
  const authHeader = request.headers.get("authorization");

  if (!REVALIDATION_SECRET) {
    return NextResponse.json({ error: "Revalidation token not configured" }, { status: 503 });
  }

  if (!hasValidBearerToken(authHeader)) {
    const expectedSecret = process.env.EDGE_REVALIDATION_SECRET;
    const providedToken = authHeader?.startsWith("Bearer ")
      ? authHeader.substring(7)
      : "NONE";
    const expectedPrefix = expectedSecret
      ? expectedSecret.substring(0, 4)
      : "UNDEFINED";
    const providedPrefix = providedToken !== "NONE"
      ? providedToken.substring(0, 4)
      : "NONE";

    console.error(
      `[AUTH SHIELD] Rejecting payload. Expected prefix: ${expectedPrefix}*** | Provided prefix: ${providedPrefix}***`,
    );
    return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
  }

  let slug = "";
  let tag = "";
  let paths: string[] = [];
  let tags: string[] = [];
  try {
    const body = (await request.json()) as {
      slug?: string;
      tag?: string;
      paths?: unknown;
      tags?: unknown;
    };
    slug = (body.slug ?? "").trim();
    tag = (body.tag ?? "").trim();
    paths = collectUniqueStrings(body.paths);
    tags = collectUniqueStrings(body.tags);
  } catch {
    return NextResponse.json({ error: "Invalid payload" }, { status: 400 });
  }

  if (!slug && !tag && paths.length === 0 && tags.length === 0) {
    return NextResponse.json({ error: "Slug, tag, paths, or tags required" }, { status: 400 });
  }

  const revalidated = new Set<string>();

  if (slug) {
    revalidatePath(`/cabins/${slug}`);
    revalidateTag(`seo-patch-${slug}`, { expire: 0 });
    revalidated.add(`path:/cabins/${slug}`);
    revalidated.add(`tag:seo-patch-${slug}`);
  }

  if (tag) {
    revalidateTag(tag, { expire: 0 });
    revalidated.add(`tag:${tag}`);
  }

  for (const path of paths) {
    revalidatePath(path);
    revalidated.add(`path:${path}`);
  }

  for (const currentTag of tags) {
    revalidateTag(currentTag, { expire: 0 });
    revalidated.add(`tag:${currentTag}`);
  }

  return NextResponse.json({
    revalidated: true,
    slug: slug || null,
    tag: tag || null,
    paths,
    tags,
    targets: [...revalidated],
    now: Date.now(),
  });
}
