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
});
