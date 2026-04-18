import {
  BackendConnectionError,
  fetchBackendHealth,
} from "@/lib/server/fortress-backend";

export const dynamic = "force-dynamic";

function getErrorMessage(error: unknown): string {
  if (error instanceof BackendConnectionError) {
    return error.message;
  }

  if (error instanceof Error) {
    return error.message;
  }

  return "Unknown backend connectivity error.";
}

export default async function ConnectivityPage() {
  const result = await fetchBackendHealth()
    .then((health) => ({ health, error: null as null }))
    .catch((error: unknown) => ({ health: null, error: getErrorMessage(error) }));

  return (
    <main className="mx-auto flex min-h-screen max-w-3xl flex-col gap-6 px-6 py-12">
      <header className="space-y-2">
        <h1 className="text-3xl font-semibold tracking-tight">
          Fortress Prime Connectivity
        </h1>
        <p className="text-sm text-muted-foreground">
          Live DGX Spark health status through Cloudflare Tunnel.
        </p>
      </header>

      <section
        className={
          result.health
            ? "rounded-lg border border-emerald-500/30 bg-emerald-500/5 p-6"
            : "rounded-lg border border-red-500/30 bg-red-500/5 p-6"
        }
      >
        <div className="flex items-center justify-between">
          <span className="text-sm font-medium">Status</span>
          <span
            className={
              result.health
                ? "text-sm font-semibold text-emerald-600"
                : "text-sm font-semibold text-red-600"
            }
          >
            {result.health ? "CONNECTED" : "DISCONNECTED"}
          </span>
        </div>
      </section>

      {result.health ? (
        <dl className="grid gap-4 rounded-lg border p-6">
          <div className="flex items-center justify-between gap-4">
            <dt className="text-sm text-muted-foreground">Service</dt>
            <dd className="text-sm font-medium">{result.health.service}</dd>
          </div>

          <div className="flex items-center justify-between gap-4">
            <dt className="text-sm text-muted-foreground">Environment</dt>
            <dd className="text-sm font-medium">{result.health.environment}</dd>
          </div>

          <div className="flex items-center justify-between gap-4">
            <dt className="text-sm text-muted-foreground">Version</dt>
            <dd className="text-sm font-medium">{result.health.version}</dd>
          </div>

          <div className="flex items-center justify-between gap-4">
            <dt className="text-sm text-muted-foreground">Ingress</dt>
            <dd className="text-sm font-medium">{result.health.ingress}</dd>
          </div>

          <div className="flex items-center justify-between gap-4">
            <dt className="text-sm text-muted-foreground">Backend Host</dt>
            <dd className="text-sm font-medium">{result.health.request_host}</dd>
          </div>

          <div className="flex items-center justify-between gap-4">
            <dt className="text-sm text-muted-foreground">Timestamp</dt>
            <dd className="text-sm font-medium">{result.health.timestamp_utc}</dd>
          </div>
        </dl>
      ) : (
        <dl className="grid gap-4 rounded-lg border p-6">
          <div className="flex items-center justify-between gap-4">
            <dt className="text-sm text-muted-foreground">Reason</dt>
            <dd className="text-sm font-medium">{result.error}</dd>
          </div>
        </dl>
      )}
    </main>
  );
}
