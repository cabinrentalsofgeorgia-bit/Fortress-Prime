import "server-only";

import { z } from "zod";

const backendHealthSchema = z.object({
  status: z.literal("ok"),
  service: z.literal("fortress-prime-backend"),
  environment: z.string().min(1),
  version: z.string().min(1),
  timestamp_utc: z.string().datetime({ offset: true }),
  ingress: z.literal("command_center"),
  request_host: z.string().min(1),
});

export type BackendHealth = z.infer<typeof backendHealthSchema>;

export class BackendConnectionError extends Error {
  readonly statusCode?: number;

  constructor(message: string, statusCode?: number) {
    super(message);
    this.name = "BackendConnectionError";
    this.statusCode = statusCode;
  }
}

function requiredEnv(
  name: "FORTRESS_BACKEND_BASE_URL" | "FORTRESS_INTERNAL_API_TOKEN",
): string {
  const value = process.env[name]?.trim();

  if (!value) {
    throw new BackendConnectionError(
      `Missing required environment variable: ${name}`,
    );
  }

  return value;
}

function getBackendBaseUrl(): URL {
  const url = new URL(requiredEnv("FORTRESS_BACKEND_BASE_URL"));

  if (url.protocol !== "https:") {
    throw new BackendConnectionError(
      "FORTRESS_BACKEND_BASE_URL must use https.",
    );
  }

  return new URL(url.toString().replace(/\/$/, "") + "/");
}

export async function fetchBackendHealth(): Promise<BackendHealth> {
  const sharedSecret = requiredEnv("FORTRESS_INTERNAL_API_TOKEN");
  const target = new URL("internal/health", getBackendBaseUrl());

  const response = await fetch(target, {
    method: "GET",
    headers: {
      Accept: "application/json",
      Authorization: `Bearer ${sharedSecret}`,
      "X-Fortress-Ingress": "command_center",
      "X-Fortress-Tunnel-Signature": sharedSecret,
    },
    cache: "no-store",
    next: { revalidate: 0 },
    redirect: "error",
    signal: AbortSignal.timeout(5_000),
  });

  if (!response.ok) {
    throw new BackendConnectionError(
      `Backend health probe failed: ${response.status} ${response.statusText}`,
      response.status,
    );
  }

  const payload: unknown = await response.json();
  return backendHealthSchema.parse(payload);
}
