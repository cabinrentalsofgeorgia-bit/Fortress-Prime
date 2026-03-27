import "server-only";

const DEFAULT_BACKEND_BASE_URL = "http://127.0.0.1:8100";

export function getBackendBaseUrl(): string {
  const backendUrl = process.env.FGP_BACKEND_URL?.trim();
  if (!backendUrl) {
    return DEFAULT_BACKEND_BASE_URL;
  }
  return backendUrl.replace(/\/$/, "");
}

export function buildBackendUrl(path: string): string {
  const normalizedPath = path.startsWith("/") ? path : `/${path}`;
  return `${getBackendBaseUrl()}${normalizedPath}`;
}
