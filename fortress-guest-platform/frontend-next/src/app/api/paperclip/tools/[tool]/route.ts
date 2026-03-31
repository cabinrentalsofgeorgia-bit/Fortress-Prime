import { NextRequest, NextResponse } from "next/server";
import { proxyPaperclipTool } from "@/app/api/_lib/paperclip-tool-proxy";

export const maxDuration = 600;
export const dynamic = "force-dynamic";

async function proxy(
  request: NextRequest,
  { params }: { params: Promise<{ tool: string }> },
) {
  const { tool } = await params;
  if (!tool) {
    return NextResponse.json({ detail: "Tool path is required." }, { status: 400 });
  }
  return proxyPaperclipTool(request, `/api/paperclip/tools/${tool}`);
}

export const GET = proxy;
export const POST = proxy;
