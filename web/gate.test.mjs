// node --test gate.test.mjs — the page's lock, without a browser.
import assert from "node:assert/strict";
import test from "node:test";
import { cookieToken, decide, hostAllowed, isLocal, sameToken, withoutToken } from "./gate.mjs";

const env = { DASHBOARD_TOKEN: "t0ken-abcdefghijklmnopqrstuvwx", DASHBOARD_HOSTS: "192.168.1.20" };
const req = (o) => ({ remoteAddress: "192.168.1.30", host: "192.168.1.20:3000", path: "/", query: "", cookie: "", ...o });

test("this Mac is decided by its socket, not by a Host header anyone can type", () => {
  assert.equal(decide(req({ remoteAddress: "127.0.0.1", host: "127.0.0.1:3000" }), env), "open");
  assert.equal(decide(req({ remoteAddress: "::ffff:127.0.0.1", host: "localhost:3000" }), env), "open");
  assert.equal(decide(req({ host: "localhost:3000" }), env), "refuse");   // a LAN device typing Host: localhost
  assert.ok(isLocal("::1") && !isLocal("192.168.1.30"));
});

test("another device needs the token: once in the link, then as a cookie", () => {
  assert.equal(decide(req({}), env), "refuse");
  assert.equal(decide(req({ query: `token=${env.DASHBOARD_TOKEN}` }), env), "pair");
  assert.equal(decide(req({ cookie: `a=1; copilot_token=${env.DASHBOARD_TOKEN}` }), env), "open");
  assert.equal(decide(req({ cookie: "copilot_token=wrong" }), env), "refuse");
  assert.equal(decide(req({ query: "token=wrong" }), env), "refuse");
});

test("no token configured means only this Mac", () => {
  assert.equal(decide(req({ query: "token=anything" }), { DASHBOARD_HOSTS: "192.168.1.20" }), "refuse");
});

test("a Host that is not this Mac is refused, even from this Mac (DNS rebinding)", () => {
  assert.equal(decide(req({ remoteAddress: "127.0.0.1", host: "attacker.example:3000" }), env), "refuse-host");
  assert.ok(hostAllowed("[::1]:3000", []) && hostAllowed("192.168.1.20:3000", ["192.168.1.20"]));
  assert.ok(!hostAllowed("192.168.1.21:3000", ["192.168.1.20"]) && !hostAllowed(undefined, []));
});

test("build files carry no data and load unpaired", () => {
  assert.equal(decide(req({ path: "/_next/static/chunks/app.js" }), env), "open");
});

test("tokens compare in constant time and cookies parse", () => {
  assert.ok(sameToken("abc", "abc") && !sameToken("abc", "abd") && !sameToken("", "abc"));
  assert.equal(cookieToken("x=1; copilot_token=a%3Db"), "a=b");
});

test("after pairing, the token leaves the URL and everything else stays", () => {
  assert.equal(withoutToken("/", "?token=abc"), "/");
  assert.equal(withoutToken("/", "?token=abc&tab=market"), "/?tab=market");
  assert.equal(withoutToken("/journal", "?tab=x&token=abc"), "/journal?tab=x");
  assert.equal(withoutToken("/", ""), "/");
});
