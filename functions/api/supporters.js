// Cloudflare Pages Function — GET /api/supporters, the names the home page
// shows under the Ko-fi button, newest first. They arrive through the Ko-fi
// webhook (api/kofi.js), which keeps only the donations left public.
//
// Answers an empty list rather than an error when there is nothing yet —
// no D1 binding, or no table because Ko-fi has never called — so the page
// simply leaves the strip hidden.

import { MAX_NAMES } from "../_lib/supporters.js";

export async function onRequestGet({ env }) {
  let names = [];
  try {
    if (env.DB) {
      const { results } = await env.DB.prepare(
        "SELECT name FROM kofi_supporters GROUP BY name ORDER BY MAX(ts) DESC LIMIT ?"
      ).bind(MAX_NAMES).all();
      names = results.map((row) => row.name);
    }
  } catch (err) {
    if (!/no such table/i.test(err.message)) console.error("supporters:", err.message);
  }
  return Response.json(
    { names },
    { headers: { "cache-control": "public, max-age=300" } }
  );
}
