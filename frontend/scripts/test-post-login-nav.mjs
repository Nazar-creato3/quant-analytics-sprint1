/**
 * Login redirect helpers — run: node frontend/scripts/test-post-login-nav.mjs
 */
import assert from "node:assert/strict";

function safeRedirectPath(from) {
  if (!from || !from.startsWith("/") || from.startsWith("//")) return "/";
  return from;
}

assert.equal(safeRedirectPath(null), "/");
assert.equal(safeRedirectPath("/dashboard"), "/dashboard");
assert.equal(safeRedirectPath("//evil.com"), "/");
assert.equal(safeRedirectPath("https://evil.com"), "/");

console.log("post-login-nav: ok");
