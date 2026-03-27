import { NextResponse } from "next/server";

export const dynamic = "force-dynamic";
export const runtime = "nodejs";
export const maxDuration = 30;

export async function POST() {
  return NextResponse.json(
    {
      detail:
        "Deprecated endpoint. Start a council job via /api/legal/cases/{slug}/deliberate and consume SSE from /api/legal/council/{jobId}/stream.",
    },
    { status: 410 },
  );
}
