import { revalidateTag } from "next/cache";
import { NextRequest, NextResponse } from "next/server";

const REVALIDATION_SECRET = process.env.EDGE_REVALIDATION_SECRET ?? "";

export async function POST(request: NextRequest) {
  const authHeader = request.headers.get("authorization");

  if (!REVALIDATION_SECRET || authHeader !== `Bearer ${REVALIDATION_SECRET}`) {
    return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
  }

  let slug: string;
  try {
    const body = (await request.json()) as { slug?: string };
    slug = (body.slug ?? "").trim();
  } catch {
    return NextResponse.json({ error: "Invalid payload" }, { status: 400 });
  }

  if (!slug) {
    return NextResponse.json({ error: "Slug required" }, { status: 400 });
  }

  revalidateTag(`seo-patch-${slug}`, { expire: 0 });

  return NextResponse.json({ revalidated: true, slug, now: Date.now() });
}
