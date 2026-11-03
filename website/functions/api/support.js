// Cloudflare Pages Function — POST /api/support, the website support form.
//
// The form on the home page (#support in website/index.html) sends a report:
//   - model    (required) the PC the device runs on;
//   - problem  (required) what is wrong;
//   - email    (required) where to reply;
//   - file     (optional) a diagnostics .zip, up to 10 MB.
// A hidden "website" field is a honeypot: a filled one is a bot, answered 200
// and dropped.
//
// What happens to a report:
//   - the .zip, if any, goes to R2 (binding SUPPORT_BUCKET) under support/<id>.zip;
//   - the fields go to D1 (binding DB, the same osmium-downloads database), table
//     support_requests (website/analytics/04_support.sql);
//   - a short notice is emailed to support@osmiumsound.it via Email Routing
//     (binding SEND_EMAIL), best-effort — if the binding is missing or the send
//     fails, the report is already stored, so the request still succeeds.
// No IP address or user-agent is stored, to match the site's aggregate-only
// analytics.
//
// Setup, once (Cloudflare dashboard → Pages project osmium-sound → Settings →
// Bindings, since the site deploys with `wrangler pages deploy`):
//   - R2 bucket binding SUPPORT_BUCKET → bucket osmium-support
//       (npx wrangler r2 bucket create osmium-support);
//   - D1 binding DB → osmium-downloads (already present);
//   - Email binding SEND_EMAIL (send_email). osmiumsound.it must be onboarded
//     to Email Sending and support@osmiumsound.it must be a verified
//     destination. Without this binding the form still works (no email).

const MAX_ZIP = 10 * 1024 * 1024;        // 10 MB, matches the client cap
const MAX_BODY = MAX_ZIP + 256 * 1024;   // zip + room for the text fields
const MAX_MODEL = 120;
const MAX_PROBLEM = 4000;
const MAX_EMAIL = 200;
const NOTIFY_TO = "support@osmiumsound.it";
const NOTIFY_FROM = "noreply@osmiumsound.it";

const SCHEMA = `CREATE TABLE IF NOT EXISTS support_requests (
  id         TEXT PRIMARY KEY,
  created_at INTEGER NOT NULL,
  model      TEXT NOT NULL,
  problem    TEXT NOT NULL,
  email      TEXT NOT NULL DEFAULT '',
  r2_key     TEXT NOT NULL DEFAULT '',
  size       INTEGER NOT NULL DEFAULT 0,
  notified   INTEGER NOT NULL DEFAULT 0
)`;

function json(status, obj) {
  return new Response(JSON.stringify(obj), {
    status,
    headers: { "content-type": "application/json", "cache-control": "no-store" },
  });
}

// Drop control chars and bidi overrides, collapse whitespace, cap length.
function clean(raw, max) {
  if (typeof raw !== "string") return "";
  const text = raw
    .normalize("NFC")
    .replace(/[\p{Cc}‎‏‪-‮⁦-⁩]/gu, " ")
    .replace(/[ \t\f\v]+/g, " ")
    .replace(/\s*\n\s*/g, "\n")
    .trim();
  const chars = [...text];
  return chars.length <= max ? text : chars.slice(0, max).join("");
}

// A short, human-quotable reference: SR-<base36 time>-<4 random>.
function newId() {
  const t = Date.now().toString(36).toUpperCase();
  const r = Math.random().toString(36).slice(2, 6).toUpperCase();
  return `SR-${t}-${r}`;
}

const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

async function looksLikeZip(file) {
  // ZIP local-file or empty-archive signature: "PK\x03\x04" / "PK\x05\x06".
  const head = new Uint8Array(await file.slice(0, 4).arrayBuffer());
  return head[0] === 0x50 && head[1] === 0x4b &&
         (head[2] === 0x03 || head[2] === 0x05) &&
         (head[3] === 0x04 || head[3] === 0x06);
}

async function notify(env, rec, hasZip) {
  if (!env.SEND_EMAIL) return false;
  const line = (k, v) => `${k}: ${v}`;
  const text = [
    line("Reference", rec.id),
    line("PC model", rec.model),
    line("Reply to", rec.email || "(not given)"),
    line("Attachment", hasZip ? `yes — R2 ${rec.r2_key} (${rec.size} bytes)` : "none"),
    "",
    "Problem:",
    rec.problem,
  ].join("\n");
  try {
    // Cloudflare refuses a `from` outside an onboarded domain, so the sender
    // address stays on ours; the reporter's address goes in the display name
    // and in Reply-To, so the support inbox reads as if they wrote, and a
    // plain reply reaches them.
    await env.SEND_EMAIL.send({
      from: { email: NOTIFY_FROM, name: rec.email },
      to: NOTIFY_TO,
      replyTo: rec.email,
      subject: `Support report ${rec.id} — ${rec.model}`.slice(0, 180),
      text,
    });
    return true;
  } catch (err) {
    console.error("support notify:", err?.code || err?.message || err);
    return false;
  }
}

export async function onRequestPost(context) {
  const { request, env } = context;
  if (!env.DB || !env.SUPPORT_BUCKET) return json(503, { ok: false, error: "not configured" });

  const len = Number(request.headers.get("content-length") || 0);
  if (len && len > MAX_BODY) return json(413, { ok: false, error: "too large" });

  let form;
  try {
    form = await request.formData();
  } catch {
    return json(400, { ok: false, error: "bad request" });
  }

  // Honeypot: a real browser leaves it empty. Pretend it worked.
  if (clean(form.get("website"), 10)) return json(200, { ok: true });

  const model = clean(form.get("model"), MAX_MODEL);
  const problem = clean(form.get("problem"), MAX_PROBLEM);
  const email = clean(form.get("email"), MAX_EMAIL);
  if (!model || !problem || !email) return json(400, { ok: false, error: "missing fields" });
  if (!EMAIL_RE.test(email)) return json(400, { ok: false, error: "bad email" });

  const id = newId();
  let r2_key = "";
  let size = 0;

  const file = form.get("file");
  if (file && typeof file === "object" && file.size > 0) {
    if (file.size > MAX_ZIP) return json(413, { ok: false, error: "attachment too large" });
    if (!/\.zip$/i.test(file.name || "") || !(await looksLikeZip(file))) {
      return json(400, { ok: false, error: "attachment must be a .zip" });
    }
    r2_key = `support/${id}.zip`;
    size = file.size;
    try {
      await env.SUPPORT_BUCKET.put(r2_key, file.stream(), {
        httpMetadata: { contentType: "application/zip" },
        customMetadata: { id, model: model.slice(0, 256) },
      });
    } catch (err) {
      console.error("support r2 put:", err?.message || err);
      return json(500, { ok: false, error: "storage" });
    }
  }

  const rec = { id, model, problem, email, r2_key, size };
  const notified = await notify(env, rec, !!r2_key);

  try {
    await env.DB.batch([
      env.DB.prepare(SCHEMA),
      env.DB.prepare(
        `INSERT INTO support_requests (id, created_at, model, problem, email, r2_key, size, notified)
         VALUES (?, ?, ?, ?, ?, ?, ?, ?)`
      ).bind(id, Date.now(), model, problem, email, r2_key, size, notified ? 1 : 0),
    ]);
  } catch (err) {
    console.error("support d1 insert:", err?.message || err);
    // The zip (if any) is already in R2 and, if configured, the notice was
    // emailed — so the report is not lost. Report success to the visitor.
    return json(200, { ok: true, id });
  }

  return json(200, { ok: true, id });
}
