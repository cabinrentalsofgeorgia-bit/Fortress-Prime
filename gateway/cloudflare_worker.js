/**
 * FORTRESS PRIME — Cloudflare Worker (Edge Gateway)
 * ===================================================
 * Implements the JWT Auth Flow from REQUIREMENTS.md Section 2.1.
 *
 * This Worker sits at api.crog-ai.com and handles ALL ingress traffic:
 *   1. JWT verification (HS256 signed by the local gateway)
 *   2. Hardware Key binding — only Gary's specific key fingerprint can trigger TITAN
 *   3. Rate limiting (100 req/min default per API key)
 *   4. PII stripping from request logs (Constitution Article I)
 *   5. Routing to the local cluster via Cloudflare Tunnel
 *
 * DEFCON TITAN Gating:
 *   The /v1/sovereign/titan/* endpoints require a JWT with:
 *     - role: "admin"
 *     - hardware_key: matching GARY_HARDWARE_KEY_FINGERPRINT
 *   This ensures ONLY Gary (via his specific hardware key) can trigger
 *   a DEFCON TITAN mode load on the Spark cluster.
 *
 * Environment Variables (set in Cloudflare Worker Settings):
 *   JWT_SECRET            — Same HS256 secret as gateway/auth.py
 *   GARY_HW_FINGERPRINT   — SHA-256 fingerprint of Gary's hardware key
 *   TUNNEL_HOSTNAME       — Backend ingress hostname (e.g., api.cabin-rentals-of-georgia.com)
 *   RATE_LIMIT_KV         — KV namespace binding for rate limiting state
 *
 * Deployment:
 *   wrangler publish gateway/cloudflare_worker.js
 *
 * Governing Documents:
 *   CONSTITUTION.md  — Article I (Data Sovereignty), Article II (Hierarchy)
 *   REQUIREMENTS.md  — Section 2.1 (Edge Gateway), Section 5 (Security)
 */

// =============================================================================
// I. CONFIGURATION
// =============================================================================

const RATE_LIMIT_WINDOW = 60;           // seconds
const DEFAULT_RATE_LIMIT = 100;         // requests per window
const TITAN_RATE_LIMIT = 5;             // TITAN requests are expensive
const PUBLIC_PATHS = new Set([
  '/',
  '/health',
  '/docs',
  '/openapi.json',
  '/redoc',
]);

// Trusted machine-to-machine bridge paths. The backend verifies the swarm Bearer
// token itself, so the edge should rate-limit and forward these requests rather
// than forcing the generic JWT/API key contract used by browser/public clients.
const SWARM_BRIDGE_PATHS = [
  '/api/agent/tools/',
  '/api/paperclip/tools/',
  '/api/agent/execute',
  '/api/paperclip/execute',
];

// Paths that require TITAN-level auth (hardware key + admin role)
const TITAN_PATHS = [
  '/v1/sovereign/titan',
  '/v1/sovereign/defcon',
];

// PII field names to strip from logged request bodies
const PII_FIELDS = new Set([
  'email', 'phone', 'ssn', 'social_security', 'password',
  'credit_card', 'card_number', 'account_number', 'owner_name',
  'guest_name', 'first_name', 'last_name', 'address',
]);

// =============================================================================
// II. JWT VERIFICATION (HS256 — matches gateway/auth.py)
// =============================================================================

/**
 * Verify a JWT token using HS256.
 * @param {string} token - The JWT string
 * @param {string} secret - The HS256 secret key
 * @returns {object|null} - Decoded payload or null if invalid
 */
async function verifyJWT(token, secret) {
  try {
    const parts = token.split('.');
    if (parts.length !== 3) return null;

    const [headerB64, payloadB64, signatureB64] = parts;

    // Import the secret as an HMAC key
    const encoder = new TextEncoder();
    const keyData = encoder.encode(secret);
    const cryptoKey = await crypto.subtle.importKey(
      'raw',
      keyData,
      { name: 'HMAC', hash: 'SHA-256' },
      false,
      ['verify']
    );

    // Verify the signature
    const signedContent = encoder.encode(`${headerB64}.${payloadB64}`);
    const signatureBytes = base64UrlDecode(signatureB64);

    const valid = await crypto.subtle.verify(
      'HMAC',
      cryptoKey,
      signatureBytes,
      signedContent
    );

    if (!valid) return null;

    // Decode payload
    const payload = JSON.parse(atob(payloadB64.replace(/-/g, '+').replace(/_/g, '/')));

    // Check expiration
    if (payload.exp && payload.exp < Math.floor(Date.now() / 1000)) {
      return null; // Token expired
    }

    return payload;

  } catch (e) {
    return null;
  }
}

/**
 * Decode a base64url string to ArrayBuffer.
 */
function base64UrlDecode(str) {
  str = str.replace(/-/g, '+').replace(/_/g, '/');
  const pad = str.length % 4;
  if (pad) str += '='.repeat(4 - pad);
  const binary = atob(str);
  const bytes = new Uint8Array(binary.length);
  for (let i = 0; i < binary.length; i++) {
    bytes[i] = binary.charCodeAt(i);
  }
  return bytes.buffer;
}

// =============================================================================
// III. RATE LIMITING (Token Bucket via KV)
// =============================================================================

/**
 * Check and enforce rate limits using Cloudflare KV.
 * @param {string} key - Rate limit key (e.g., API key hash or IP)
 * @param {number} limit - Max requests per window
 * @param {KVNamespace} kv - Cloudflare KV binding
 * @returns {object} - { allowed: bool, remaining: number, reset: number }
 */
async function checkRateLimit(key, limit, kv) {
  if (!kv) return { allowed: true, remaining: limit, reset: 0 };

  const rlKey = `rl:${key}`;
  const now = Math.floor(Date.now() / 1000);
  const windowStart = now - (now % RATE_LIMIT_WINDOW);

  const raw = await kv.get(rlKey);
  let bucket = raw ? JSON.parse(raw) : { window: windowStart, count: 0 };

  // Reset if window has passed
  if (bucket.window !== windowStart) {
    bucket = { window: windowStart, count: 0 };
  }

  bucket.count++;

  const allowed = bucket.count <= limit;
  const remaining = Math.max(0, limit - bucket.count);
  const reset = windowStart + RATE_LIMIT_WINDOW;

  // Persist (fire and forget — KV is eventually consistent)
  await kv.put(rlKey, JSON.stringify(bucket), {
    expirationTtl: RATE_LIMIT_WINDOW * 2,
  });

  return { allowed, remaining, reset };
}

// =============================================================================
// IV. PII SCRUBBING (Constitution Article I)
// =============================================================================

/**
 * Strip PII fields from an object for safe logging.
 * NEVER logs: email, phone, SSN, passwords, owner names, guest names.
 */
function scrubPII(obj) {
  if (!obj || typeof obj !== 'object') return obj;

  const scrubbed = {};
  for (const [key, value] of Object.entries(obj)) {
    if (PII_FIELDS.has(key.toLowerCase())) {
      scrubbed[key] = '[REDACTED]';
    } else if (typeof value === 'object' && value !== null) {
      scrubbed[key] = scrubPII(value);
    } else {
      scrubbed[key] = value;
    }
  }
  return scrubbed;
}

// =============================================================================
// V. TITAN GATING (Constitution Article II — Hardware Key Required)
// =============================================================================

/**
 * Check if a request is authorized for TITAN-level operations.
 *
 * Requirements:
 *   1. Valid JWT with role: "admin"
 *   2. JWT must contain hardware_key matching Gary's fingerprint
 *   3. Request must come from a known IP (optional additional check)
 *
 * This ensures ONLY Gary (via his specific hardware key) can trigger
 * DEFCON TITAN mode on the Spark cluster.
 */
function isTitanAuthorized(payload, env) {
  if (!payload) return false;

  // Must be admin role
  if (payload.role !== 'admin') return false;

  // Must have hardware key fingerprint matching Gary's key
  const hwFingerprint = payload.hardware_key || payload.hw_fp;
  const requiredFingerprint = env.GARY_HW_FINGERPRINT;

  if (!requiredFingerprint) {
    // If fingerprint not configured, TITAN is locked out entirely
    console.error('GARY_HW_FINGERPRINT not set — TITAN access denied');
    return false;
  }

  if (!hwFingerprint || hwFingerprint !== requiredFingerprint) {
    return false;
  }

  return true;
}

/**
 * Check if a path requires TITAN-level authorization.
 */
function isTitanPath(path) {
  return TITAN_PATHS.some(prefix => path.startsWith(prefix));
}

function isSwarmBridgePath(path) {
  return SWARM_BRIDGE_PATHS.some(prefix => path.startsWith(prefix));
}

// =============================================================================
// VI. MAIN HANDLER
// =============================================================================

export default {
  async fetch(request, env, ctx) {
    const url = new URL(request.url);
    const path = url.pathname;
    const method = request.method;

    // --- CORS Preflight ---
    if (method === 'OPTIONS') {
      return new Response(null, {
        status: 204,
        headers: {
          'Access-Control-Allow-Origin': '*',
          'Access-Control-Allow-Methods': 'GET, POST, PUT, DELETE, OPTIONS',
          'Access-Control-Allow-Headers': 'Content-Type, Authorization',
          'Access-Control-Max-Age': '86400',
        },
      });
    }

    // --- Public Paths (no auth required) ---
    if (PUBLIC_PATHS.has(path)) {
      return proxyToTunnel(request, env, path);
    }

    // --- Extract Token ---
    const authHeader = request.headers.get('Authorization') || '';
    let token = null;
    let authMethod = 'none';

    if (authHeader.startsWith('Bearer ')) {
      token = authHeader.slice(7);
      authMethod = 'jwt';
    } else if (authHeader.startsWith('ApiKey ')) {
      // API keys are verified by the local gateway, not here.
      // We just rate-limit and forward.
      authMethod = 'api_key';
    }

    const swarmBridgePath = isSwarmBridgePath(path);

    // --- JWT Verification ---
    let payload = null;
    if (swarmBridgePath && authMethod === 'jwt') {
      // Trusted bridge path: forward the Bearer token upstream and let the
      // sovereign backend validate the swarm token contract.
      authMethod = 'swarm_bridge';
    } else if (authMethod === 'jwt') {
      payload = await verifyJWT(token, env.JWT_SECRET);
      if (!payload) {
        return jsonResponse(401, {
          error: 'Invalid or expired JWT',
          hint: 'Obtain a token from /v1/auth/login on the local gateway',
        });
      }
    } else if (authMethod === 'none') {
      return jsonResponse(401, {
        error: 'Authentication required',
        methods: ['Bearer <jwt>', 'ApiKey <key>'],
      });
    }

    // --- TITAN Path Gating ---
    if (isTitanPath(path)) {
      if (authMethod !== 'jwt') {
        return jsonResponse(403, {
          error: 'TITAN operations require JWT authentication (hardware key bound)',
          hint: 'API keys cannot trigger DEFCON changes',
        });
      }

      if (!isTitanAuthorized(payload, env)) {
        // Log the attempt (without PII)
        console.warn(`TITAN access DENIED: role=${payload?.role}, hw_key=${payload?.hardware_key ? 'present' : 'missing'}`);
        return jsonResponse(403, {
          error: 'TITAN access denied',
          reason: 'Requires admin role with hardware key authentication',
          article: 'Constitution Article II, Section 2.1 — Human Override Authority',
        });
      }

      console.log(`TITAN access GRANTED: user=${payload.username}`);
    }

    // --- Rate Limiting ---
    const rlKey = payload
      ? `user:${payload.sub}`
      : authMethod === 'swarm_bridge'
        ? `swarm:${request.headers.get('CF-Connecting-IP') || 'unknown'}`
        : `ip:${request.headers.get('CF-Connecting-IP')}`;
    const rlLimit = isTitanPath(path) ? TITAN_RATE_LIMIT : DEFAULT_RATE_LIMIT;
    const rl = await checkRateLimit(rlKey, rlLimit, env.RATE_LIMIT_KV);

    if (!rl.allowed) {
      return jsonResponse(429, {
        error: 'Rate limit exceeded',
        limit: rlLimit,
        window_seconds: RATE_LIMIT_WINDOW,
        reset_at: new Date(rl.reset * 1000).toISOString(),
      }, {
        'X-RateLimit-Limit': rlLimit.toString(),
        'X-RateLimit-Remaining': '0',
        'X-RateLimit-Reset': rl.reset.toString(),
        'Retry-After': (rl.reset - Math.floor(Date.now() / 1000)).toString(),
      });
    }

    // --- Proxy to Local Cluster (via Cloudflare Tunnel) ---
    const response = await proxyToTunnel(request, env, path);

    // Add rate limit headers to response
    const headers = new Headers(response.headers);
    headers.set('X-RateLimit-Limit', rlLimit.toString());
    headers.set('X-RateLimit-Remaining', rl.remaining.toString());
    headers.set('X-RateLimit-Reset', rl.reset.toString());
    headers.set('X-Fortress-Node', 'cloudflare-edge');
    headers.set('X-Data-Classification', isTitanPath(path) ? 'SOVEREIGN' : 'PUBLIC');

    return new Response(response.body, {
      status: response.status,
      headers,
    });
  },
};

// =============================================================================
// VII. HELPERS
// =============================================================================

/**
 * Proxy a request to the local Fortress cluster via Cloudflare Tunnel.
 */
async function proxyToTunnel(request, env, path) {
  const tunnelHost = env.TUNNEL_HOSTNAME || 'api.cabin-rentals-of-georgia.com';
  const targetUrl = `https://${tunnelHost}${path}${new URL(request.url).search}`;

  const proxyHeaders = new Headers(request.headers);
  proxyHeaders.set('X-Forwarded-For', request.headers.get('CF-Connecting-IP') || 'unknown');
  proxyHeaders.set('X-Fortress-Edge', 'cloudflare');
  proxyHeaders.set('X-Request-ID', crypto.randomUUID());

  try {
    return await fetch(targetUrl, {
      method: request.method,
      headers: proxyHeaders,
      body: request.body,
    });
  } catch (e) {
    return jsonResponse(502, {
      error: 'Fortress cluster unreachable',
      detail: 'Cloudflare Tunnel connection failed. The cluster may be in TITAN mode transition.',
      hint: 'Check: ./switch_defcon.sh STATUS',
    });
  }
}

/**
 * Build a JSON response with optional extra headers.
 */
function jsonResponse(status, body, extraHeaders = {}) {
  const headers = {
    'Content-Type': 'application/json',
    'X-Fortress-Node': 'cloudflare-edge',
    ...extraHeaders,
  };
  return new Response(JSON.stringify(body, null, 2), { status, headers });
}
