"use server";

import { revalidatePath } from "next/cache";
import { cookies } from "next/headers";
import { buildBackendUrl } from "@/lib/server/backend-url";

const INTERNAL_API_KEY =
  process.env.INTERNAL_API_KEY || process.env.SWARM_API_KEY || "";
const SESSION_COOKIE = "fortress_session";

export type YieldPricingRecommendation = {
  start_date: string;
  end_date: string;
  adjustment_percent: number;
  rationale: string;
};

export type YieldAnalysisPayload = {
  velocity_score: number;
  friction_warning: boolean;
  pricing_recommendations: YieldPricingRecommendation[];
};

export type YieldAnalysisActionResult =
  | {
      ok: true;
      analysis: YieldAnalysisPayload;
    }
  | {
      ok: false;
      error: string;
    };

export type PricingOverridePayload = {
  id: string;
  property_id: string;
  start_date: string;
  end_date: string;
  adjustment_percentage: number;
  reason: string;
  approved_by: string;
};

export type ApproveYieldActionResult =
  | {
      ok: true;
      overrides: PricingOverridePayload[];
    }
  | {
      ok: false;
      error: string;
    };

type StaffUserPayload = {
  email: string;
  role: string;
};

async function parseErrorMessage(response: Response, fallback: string): Promise<string> {
  const payload = (await response.json().catch(() => null)) as
    | { detail?: string | { message?: string } }
    | null;
  if (!payload?.detail) return fallback;
  if (typeof payload.detail === "string") return payload.detail;
  if (typeof payload.detail.message === "string") return payload.detail.message;
  return fallback;
}

async function requireAdminSession(): Promise<string> {
  const cookieStore = await cookies();
  const token = cookieStore.get(SESSION_COOKIE)?.value;
  if (!token) {
    throw new Error("Admin session is missing. Log in again and retry.");
  }

  const response = await fetch(buildBackendUrl("/api/auth/me"), {
    method: "GET",
    headers: {
      Authorization: `Bearer ${token}`,
    },
    cache: "no-store",
  });
  if (!response.ok) {
    throw new Error(await parseErrorMessage(response, "Unable to verify the current admin session."));
  }

  const user = (await response.json()) as StaffUserPayload;
  if (user.role !== "super_admin" && user.role !== "manager") {
    throw new Error("Yield controls require a manager or super-admin session.");
  }
  return token;
}

function buildOverrideReason(rationale: string): string {
  const normalized = `Yield Swarm approved override: ${rationale.trim()}`.trim();
  return normalized.slice(0, 500);
}

export async function runYieldSwarmAnalysis(input: {
  propertyId: string;
  daysBack?: number;
  windowDays?: number;
}): Promise<YieldAnalysisActionResult> {
  try {
    await requireAdminSession();
    if (!INTERNAL_API_KEY) {
      return { ok: false, error: "Internal swarm key is not configured." };
    }

    const response = await fetch(buildBackendUrl("/api/swarm/financial/analyze"), {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-Swarm-Token": INTERNAL_API_KEY,
      },
      cache: "no-store",
      body: JSON.stringify({
        property_id: input.propertyId,
        days_back: input.daysBack ?? 7,
        window_days: input.windowDays ?? 30,
      }),
    });
    if (!response.ok) {
      return {
        ok: false,
        error: await parseErrorMessage(response, "Yield analysis failed."),
      };
    }

    const analysis = (await response.json()) as YieldAnalysisPayload;
    return { ok: true, analysis };
  } catch (error) {
    return {
      ok: false,
      error: error instanceof Error ? error.message : "Yield analysis failed.",
    };
  }
}

export async function approveYieldRecommendations(input: {
  propertyId: string;
  recommendations: YieldPricingRecommendation[];
}): Promise<ApproveYieldActionResult> {
  try {
    const token = await requireAdminSession();
    if (input.recommendations.length === 0) {
      return { ok: false, error: "No pricing recommendations are available to approve." };
    }

    const responses = await Promise.all(
      input.recommendations.map(async (recommendation) => {
        const response = await fetch(buildBackendUrl("/api/pricing/overrides"), {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            Authorization: `Bearer ${token}`,
          },
          cache: "no-store",
          body: JSON.stringify({
            property_id: input.propertyId,
            start_date: recommendation.start_date,
            end_date: recommendation.end_date,
            adjustment_percentage: recommendation.adjustment_percent,
            reason: buildOverrideReason(recommendation.rationale),
          }),
        });
        if (!response.ok) {
          throw new Error(await parseErrorMessage(response, "Failed to write pricing override."));
        }
        return (await response.json()) as PricingOverridePayload;
      }),
    );

    revalidatePath("/command/yield");
    return { ok: true, overrides: responses };
  } catch (error) {
    return {
      ok: false,
      error: error instanceof Error ? error.message : "Failed to approve yield recommendations.",
    };
  }
}
