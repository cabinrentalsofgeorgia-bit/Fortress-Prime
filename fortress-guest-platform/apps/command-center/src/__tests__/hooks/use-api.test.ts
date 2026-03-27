import { describe, it, expect, vi, beforeEach } from "vitest";
import { api, ApiError, getToken, setToken, clearToken } from "@/lib/api";

describe("api client", () => {
  beforeEach(() => {
    clearToken();
    vi.restoreAllMocks();
  });

  it("token storage works", () => {
    expect(getToken()).toBeNull();
    setToken("test-jwt");
    expect(getToken()).toBe("test-jwt");
    clearToken();
    expect(getToken()).toBeNull();
  });

  it("api.get calls fetch with GET", async () => {
    const mockData = { id: 1, name: "Cabin" };
    vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(
      new Response(JSON.stringify(mockData), { status: 200 }),
    );

    const result = await api.get("/api/properties/");
    expect(result).toEqual(mockData);
    expect(globalThis.fetch).toHaveBeenCalledOnce();
  });

  it("api.post calls fetch with POST", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(
      new Response(JSON.stringify({ ok: true }), { status: 200 }),
    );

    const result = await api.post("/api/ai/ask", { question: "test" });
    expect(result).toEqual({ ok: true });
  });

  it("throws ApiError on non-ok response", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(
      new Response(JSON.stringify({ detail: "Not found" }), { status: 404 }),
    );

    await expect(api.get("/api/nothing")).rejects.toThrow(ApiError);
  });

  it("posts async job archive prune to system ops BFF path", async () => {
    const body = {
      matched_rows: 0,
      statuses: ["failed", "cancelled"],
      older_than_minutes: 60,
      cutoff_utc: "2026-01-01T00:00:00+00:00",
      apply: false,
      preview: [],
      preview_truncated: 0,
      archived_rows: 0,
      archive_path: null,
    };
    vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(
      new Response(JSON.stringify(body), { status: 200 }),
    );

    const result = await api.post("/api/system/ops/async-jobs/archive-prune", {
      older_than_minutes: 60,
      limit: 500,
      statuses: null,
      apply: false,
      output_path: null,
    });
    expect(result).toEqual(body);
    expect(globalThis.fetch).toHaveBeenCalledWith(
      expect.stringContaining("/api/system/ops/async-jobs/archive-prune"),
      expect.objectContaining({ method: "POST" }),
    );
  });
});
