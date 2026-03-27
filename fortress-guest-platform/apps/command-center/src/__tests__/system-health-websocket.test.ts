import { describe, expect, it, vi, beforeEach, afterEach } from "vitest";
import { buildSystemHealthWsUrl } from "@/lib/system-health-websocket";

describe("buildSystemHealthWsUrl", () => {
  const originalEnv = process.env;

  beforeEach(() => {
    vi.stubGlobal("window", { location: { origin: "https://crog-ai.com" } });
    process.env = { ...originalEnv };
  });

  afterEach(() => {
    process.env = originalEnv;
    vi.unstubAllGlobals();
  });

  it("returns null when token is empty", () => {
    expect(buildSystemHealthWsUrl("")).toBeNull();
  });

  it("appends token to explicit NEXT_PUBLIC_SYSTEM_HEALTH_WS_URL", () => {
    process.env.NEXT_PUBLIC_SYSTEM_HEALTH_WS_URL = "wss://api.example.com/api/telemetry/ws/system-health";
    const u = buildSystemHealthWsUrl("abc.def.ghi");
    expect(u).toBe("wss://api.example.com/api/telemetry/ws/system-health?token=abc.def.ghi");
  });

  it("derives from NEXT_PUBLIC_WS_URL by stripping /ws", () => {
    process.env.NEXT_PUBLIC_WS_URL = "wss://staging-api.crog-ai.com/ws";
    const u = buildSystemHealthWsUrl("tok");
    expect(u).toBe("wss://staging-api.crog-ai.com/api/telemetry/ws/system-health?token=tok");
  });
});
