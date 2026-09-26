// Cloudflare Pages Function — POST /api/kofi, the Ko-fi webhook.
//
// Ko-fi calls this once for every payment to ko-fi.com/osmiumsound, and it is
// the only way to learn who supported the project: Ko-fi has no API to read
// the list back. What is kept is what the home page shows under the Ko-fi
// button (/api/supporters): the name, and when.
//
// Kept, and nothing else:
//   - only donations and subscriptions, not shop orders or commissions;
//   - only the ones the supporter left public on Ko-fi. A private one is
//     answered and forgotten: no row, not even an anonymous one;
//   - the name as the supporter typed it on Ko-fi, cleaned up. The email
//     address, the message and the amount arrive in the same request and are
//     never written anywhere.
// The list keeps the latest MAX_NAMES different names; an older one is
// deleted when a newer one pushes it out.
//
// Setup, once:
//   - Ko-fi → Settings → More → API: webhook URL
//     https://osmiumsound.it/api/kofi, and copy the verification token;
//   - Cloudflare Pages → osmium-sound → Settings → Variables and secrets:
//     KOFI_VERIFICATION_TOKEN = that token, as a secret.
// The table creates itself on the first call. Taking a name off the list,
// when somebody asks:
//   npx wrangler d1 execute osmium-downloads --remote \
//     --command "DELETE FROM kofi_supporters WHERE name = '…'"
//
// Ko-fi sends again whatever does not get a 200, so a failed write answers
// 500 and comes back later; message_id makes the second delivery a no-op.

import { MAX_NAMES, SCHEMA, supporterOf } from "../_lib/supporters.js";

const MAX_BODY = 16384;

function sameToken(a, b) {
  if (typeof a !== "string" || typeof b !== "string" || a.length !== b.length) return false;
  let diff = 0;
  for (let i = 0; i < a.length; i++) diff |= a.charCodeAt(i) ^ b.charCodeAt(i);
  return diff === 0;
}

function reply(status, text) {
  return new Response(text, { status, headers: { "content-type": "text/plain", "cache-control": "no-store" } });
}

export async function onRequestPost(context) {
  const { request, env } = context;
  if (!env.KOFI_VERIFICATION_TOKEN || !env.DB) return reply(503, "not configured");

  let data;
  try {
    const body = await request.text();
    if (body.length > MAX_BODY) return reply(413, "too large");
    data = JSON.parse(new URLSearchParams(body).get("data") || "");
  } catch {
    return reply(400, "bad request");
  }
  if (!sameToken(data?.verification_token, env.KOFI_VERIFICATION_TOKEN)) return reply(403, "forbidden");

  const supporter = supporterOf(data);
  if (!supporter) return reply(200, "ok");

  const ts = Date.parse(data.timestamp) || Date.now();
  try {
    await env.DB.batch([
      env.DB.prepare(SCHEMA),
      env.DB.prepare("INSERT OR IGNORE INTO kofi_supporters (message_id, name, ts) VALUES (?, ?, ?)")
        .bind(supporter.id, supporter.name, ts),
      env.DB.prepare(
        `DELETE FROM kofi_supporters WHERE name NOT IN
           (SELECT name FROM kofi_supporters GROUP BY name ORDER BY MAX(ts) DESC LIMIT ?)`
      ).bind(MAX_NAMES),
    ]);
  } catch (err) {
    console.error("kofi webhook:", err.message);
    return reply(500, "retry");
  }
  return reply(200, "ok");
}
