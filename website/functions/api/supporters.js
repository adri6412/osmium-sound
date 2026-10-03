// Cloudflare Pages Function — GET /api/supporters, the cards the home page
// shows under the Ko-fi button, newest first. They arrive through the Ko-fi
// webhook (api/kofi.js), which keeps only the donations left public.
//
// One card per name: somebody who gives every month shows up once, with the
// day of the latest donation and the latest message they wrote (an empty one
// does not hide an earlier message).
//
// Answers an empty list rather than an error when there is nothing yet —
// no D1 binding, or no table because Ko-fi has never called — so the page
// simply leaves the strip hidden.

import { MAX_NAMES } from "../_lib/supporters.js";

const QUERY = `
  SELECT s.name,
         MAX(s.ts) AS ts,
         COALESCE((SELECT m.message FROM kofi_supporters m
                    WHERE m.name = s.name AND m.message <> ''
                    ORDER BY m.ts DESC LIMIT 1), '') AS message
    FROM kofi_supporters s
   GROUP BY s.name
   ORDER BY ts DESC
   LIMIT ?`;

export async function onRequestGet({ env }) {
  let supporters = [];
  try {
    if (env.DB) {
      const { results } = await env.DB.prepare(QUERY).bind(MAX_NAMES).all();
      supporters = results.map((row) => ({
        name: row.name,
        message: row.message,
        date: new Date(row.ts).toISOString().slice(0, 10),
      }));
    }
  } catch (err) {
    if (!/no such table/i.test(err.message)) console.error("supporters:", err.message);
  }
  return Response.json(
    { supporters },
    { headers: { "cache-control": "public, max-age=300" } }
  );
}
