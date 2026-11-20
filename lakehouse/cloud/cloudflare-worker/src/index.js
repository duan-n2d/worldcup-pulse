// Dispatches the GitHub Actions ETL workflow.
// The fetch handler requires `Authorization: Bearer <TRIGGER_TOKEN>` (set with
// `wrangler secret put TRIGGER_TOKEN`); without a configured token it refuses
// every request. The cron trigger is disabled in wrangler.toml, so `scheduled`
// only runs if a cron is added back.
export default {
  async scheduled(event, env, ctx) {
    ctx.waitUntil(triggerGithub(env));
  },
  async fetch(request, env) {
    if (!env.TRIGGER_TOKEN) {
      return json({ ok: false, message: "TRIGGER_TOKEN secret is not configured" }, 503);
    }
    if (!(await isAuthorized(request, env.TRIGGER_TOKEN))) {
      return json({ ok: false, message: "Unauthorized" }, 401, { "WWW-Authenticate": "Bearer" });
    }
    if (request.method !== "POST") {
      return json({ ok: false, message: "Use POST" }, 405, { "Allow": "POST" });
    }
    const result = await triggerGithub(env);
    return json(result, result.ok ? 200 : 502);
  }
};

function json(body, status = 200, extraHeaders = {}) {
  return new Response(JSON.stringify(body, null, 2), {
    status,
    headers: { "content-type": "application/json", ...extraHeaders }
  });
}

async function isAuthorized(request, expectedToken) {
  const header = request.headers.get("Authorization") || "";
  const match = header.match(/^Bearer\s+(.+)$/i);
  if (!match) {
    return false;
  }
  return timingSafeEqual(match[1].trim(), expectedToken);
}

// Compare SHA-256 digests so both inputs have equal length, then compare every
// byte without early exit.
async function timingSafeEqual(a, b) {
  const enc = new TextEncoder();
  const [da, db] = await Promise.all([
    crypto.subtle.digest("SHA-256", enc.encode(a)),
    crypto.subtle.digest("SHA-256", enc.encode(b))
  ]);
  const x = new Uint8Array(da);
  const y = new Uint8Array(db);
  let diff = 0;
  for (let i = 0; i < x.length; i++) {
    diff |= x[i] ^ y[i];
  }
  return diff === 0;
}

async function triggerGithub(env) {
  const repo = env.GITHUB_REPO;
  const token = env.GITHUB_TOKEN;
  if (!repo || !token) {
    return { ok: false, message: "Missing GITHUB_REPO or GITHUB_TOKEN secret" };
  }
  const response = await fetch(`https://api.github.com/repos/${repo}/dispatches`, {
    method: "POST",
    headers: {
      "Authorization": `Bearer ${token}`,
      "Accept": "application/vnd.github+json",
      "User-Agent": "worldcup-pulse-etl-trigger"
    },
    body: JSON.stringify({ event_type: "run-etl", client_payload: { source: "cloudflare", mode: "full" } })
  });
  const text = await response.text();
  console.log(`GitHub dispatch status=${response.status} body=${text}`);
  return { ok: response.ok, status: response.status, body: text };
}
