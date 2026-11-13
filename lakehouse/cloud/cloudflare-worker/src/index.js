export default {
  async scheduled(event, env, ctx) {
    ctx.waitUntil(triggerGithub(env));
  },
  async fetch(request, env) {
    const result = await triggerGithub(env);
    return new Response(JSON.stringify(result, null, 2), { headers: { "content-type": "application/json" } });
  }
};

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
      "User-Agent": "worldcup-pulse-cloudflare-cron"
    },
    body: JSON.stringify({ event_type: "run-etl", client_payload: { source: "cloudflare", mode: "incremental" } })
  });
  const text = await response.text();
  console.log(`GitHub dispatch status=${response.status} body=${text}`);
  return { ok: response.ok, status: response.status, body: text };
}
