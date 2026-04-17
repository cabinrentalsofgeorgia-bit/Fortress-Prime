import "server-only";

const DEFAULT_BACKEND_BASE_URL = "http://127.0.0.1:8100";

function stripWrappingQuotes(value: string): string {
  const trimmed = value.trim();
  if (
    (trimmed.startsWith('"') && trimmed.endsWith('"')) ||
    (trimmed.startsWith("'") && trimmed.endsWith("'"))
  ) {
    return trimmed.slice(1, -1).trim();
  }
  return trimmed;
}

export function getBackendBaseUrl(): string {
  const backendUrl = process.env.FGP_BACKEND_URL
    ? stripWrappingQuotes(process.env.FGP_BACKEND_URL)
    : "";
  if (!backendUrl) {
    return DEFAULT_BACKEND_BASE_URL;
  }
  return backendUrl.replace(/\/$/, "");
}

export function buildBackendUrl(path: string): string {
  const normalizedPath = path.startsWith("/") ? path : `/${path}`;
  return `${getBackendBaseUrl()}${normalizedPath}`;
}
