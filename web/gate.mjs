// Who may load the dashboard page itself.
//
// The API has asked a token of anything that is not this Mac since the phone
// was first paired. The page did not: Next renders it on the Mac, fetching
// every number from the API as "this Mac", so any device on the Wi-Fi that
// opened http://<mac>:3000 got the paper book and all the research without
// pairing, and a DNS-rebinding page could read it too. This is the same lock,
// on the page: the real socket address decides "this Mac" (a Host header can
// be typed by anyone), the Host must name this Mac, and every other device
// carries the pairing token as a cookie.
import { timingSafeEqual } from "node:crypto";
import { readFileSync } from "node:fs";

export const COOKIE = "copilot_token";
const LOCAL_ADDRESSES = new Set(["127.0.0.1", "::1", "::ffff:127.0.0.1"]);
const LOCAL_NAMES = new Set(["127.0.0.1", "localhost", "::1", "[::1]"]);
// Build output only: code and styles, no data.
const OPEN_PREFIXES = ["/_next/static/", "/favicon.ico"];

export function readEnv(path) {
  const out = {};
  try {
    for (const line of readFileSync(path, "utf8").split("\n")) {
      const i = line.indexOf("=");
      if (i > 0) out[line.slice(0, i).trim()] = line.slice(i + 1).trim().replace(/^["']|["']$/g, "");
    }
  } catch {
    // no file: no token and no paired hosts — the Mac only
  }
  return out;
}

export function isLocal(remoteAddress) {
  return LOCAL_ADDRESSES.has(remoteAddress ?? "");
}

export function hostAllowed(hostHeader, pairedHosts) {
  if (!hostHeader) return false;
  const h = hostHeader.trim().toLowerCase();
  const name = h.startsWith("[") ? h.slice(0, h.indexOf("]") + 1)
    : (h.split(":").length === 2 ? h.split(":")[0] : h);
  return LOCAL_NAMES.has(name) || pairedHosts.includes(name);
}

export function sameToken(given, expected) {
  if (!given || !expected) return false;
  const a = Buffer.from(given), b = Buffer.from(expected);
  return a.length === b.length && timingSafeEqual(a, b);
}

export function cookieToken(cookieHeader) {
  for (const part of (cookieHeader ?? "").split(";")) {
    const [k, ...v] = part.trim().split("=");
    if (k === COOKIE) return decodeURIComponent(v.join("="));
  }
  return null;
}

/** "open" | "pair" (set the cookie, then serve) | "refuse-host" | "refuse" */
export function decide({ remoteAddress, host, path, query, cookie }, env) {
  const paired = (env.DASHBOARD_HOSTS ?? "").split(",").map((s) => s.trim().toLowerCase()).filter(Boolean);
  if (!hostAllowed(host, paired)) return "refuse-host";
  if (isLocal(remoteAddress) || OPEN_PREFIXES.some((p) => path.startsWith(p))) return "open";
  const expected = env.DASHBOARD_TOKEN;
  if (sameToken(new URLSearchParams(query ?? "").get("token"), expected)) return "pair";
  if (sameToken(cookieToken(cookie), expected)) return "open";
  return "refuse";
}

// Served to a device without the token. No data. A phone paired before the
// page itself was locked holds the token in its own storage: it is sent back
// once, as the pairing link would, and becomes the cookie.
export const PAIR_PAGE = `<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>Pair this device</title>
<style>body{background:#09090b;color:#d4d4d8;font:15px/1.5 system-ui,sans-serif;margin:0;padding:48px 16px}
main{max-width:28rem;margin:auto}h1{font-size:18px;color:#fcd34d}</style></head><body><main>
<h1>This device isn't paired</h1>
<p>On the Mac, open the dashboard and choose <b>Use this on my phone</b>, then scan the code.</p>
</main><script>
try{var t=localStorage.getItem("copilot_token");
if(t&&location.search.indexOf("token=")<0){location.replace("/?token="+encodeURIComponent(t));}}catch(e){}
</script></body></html>`;
