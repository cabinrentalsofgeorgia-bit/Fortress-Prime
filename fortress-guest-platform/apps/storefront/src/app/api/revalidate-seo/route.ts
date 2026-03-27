import { revalidatePath, revalidateTag } from "next/cache";
import { NextRequest, NextResponse } from "next/server";

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
  const rawSecret = process.env.EDGE_REVALIDATION_SECRET || "";
  const expectedSecret = rawSecret.trim();

  const authHeader = request.headers.get("authorization") || "";
  const providedToken = authHeader.startsWith("Bearer ")
    ? authHeader.substring(7).trim()
    : "";

  if (!expectedSecret || providedToken !== expectedSecret) {
    console.error(
      `[AUTH SHIELD] Rejecting payload. Expected Length: ${expectedSecret.length}, Provided Length: ${providedToken.length}`,
    );
    return new Response(JSON.stringify({ detail: "Unauthorized" }), { status: 401 });
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
