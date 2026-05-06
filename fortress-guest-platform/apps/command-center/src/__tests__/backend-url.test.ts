import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("server-only", () => ({}));

describe("command center backend URL helper", () => {
  const originalEnv = process.env;

  beforeEach(() => {
    vi.resetModules();
    process.env = { ...originalEnv };
    delete process.env.FGP_BACKEND_URL;
    delete process.env.FORTRESS_BACKEND_BASE_URL;
  });

  afterEach(() => {
    process.env = originalEnv;
  });

  async function loadHelper() {
    return import("@/lib/server/backend-url");
  }

  it("prefers the local/legacy FGP_BACKEND_URL when both names are present", async () => {
    process.env.FGP_BACKEND_URL = "https://fgp-backend.example.test/";
    process.env.FORTRESS_BACKEND_BASE_URL = "https://fortress-backend.example.test/";

    const { buildBackendUrl } = await loadHelper();

    expect(buildBackendUrl("/api/auth/login")).toBe(
      "https://fgp-backend.example.test/api/auth/login",
    );
  });

  it("uses the Vercel production FORTRESS_BACKEND_BASE_URL when FGP_BACKEND_URL is absent", async () => {
    process.env.FORTRESS_BACKEND_BASE_URL = "https://fortress-backend.example.test/";

    const { buildBackendUrl } = await loadHelper();

    expect(buildBackendUrl("/api/auth/login")).toBe(
      "https://fortress-backend.example.test/api/auth/login",
    );
  });
});
