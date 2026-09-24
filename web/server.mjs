// The dashboard's production server: Next, behind the page's lock (gate.mjs).
//
//   node server.mjs --hostname 0.0.0.0 --port 3000      (npm run start -- …)
//
// A custom server because only the raw socket knows who is asking: inside Next
// a request from a phone and one from this Mac look alike, and the Host header
// is whatever the caller typed.
import { createServer } from "node:http";
import path from "node:path";
import { fileURLToPath } from "node:url";
import next from "next";
import { COOKIE, PAIR_PAGE, decide, readEnv } from "./gate.mjs";

const here = path.dirname(fileURLToPath(import.meta.url));
const ENV_PATH = path.join(here, "..", "api", ".env");
const argv = process.argv.slice(2);
const arg = (name, fallback) => (argv.includes(name) ? argv[argv.indexOf(name) + 1] : fallback);
const hostname = arg("--hostname", "127.0.0.1");
const port = Number(arg("--port", "3000"));

const app = next({ dev: false, dir: here, hostname, port });
const handle = app.getRequestHandler();
await app.prepare();

createServer((req, res) => {
  const url = new URL(req.url ?? "/", "http://placeholder");
  // Read per request: pairing and "forget paired devices" change the token,
  // and the page must follow without a restart.
  const env = readEnv(ENV_PATH);
  const verdict = decide({
    remoteAddress: req.socket.remoteAddress, host: req.headers.host,
    path: url.pathname, query: url.search, cookie: req.headers.cookie,
  }, env);
  if (verdict === "refuse-host") {
    res.writeHead(400, { "content-type": "text/plain" });
    res.end("This dashboard answers only to its own address.");
    return;
  }
  if (verdict === "refuse") {
    res.writeHead(401, { "content-type": "text/html; charset=utf-8", "cache-control": "no-store" });
    res.end(PAIR_PAGE);
    return;
  }
  if (verdict === "pair") {
    // No Secure flag: this is plain HTTP on a home network (see access.py).
    res.setHeader("set-cookie",
      `${COOKIE}=${encodeURIComponent(env.DASHBOARD_TOKEN)}; Path=/; Max-Age=31536000; HttpOnly; SameSite=Lax`);
  }
  handle(req, res);
}).listen(port, hostname, () => {
  console.log(`dashboard on http://${hostname}:${port} (other devices need the pairing token)`);
});
