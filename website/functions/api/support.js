// Cloudflare Pages Function — POST /api/support, the website support form.
//
// The form on the home page (#support in website/index.html) sends a report:
//   - model    (required) the PC the device runs on;
//   - problem  (required) what is wrong;
//   - email    (required) where to reply;
//   - files    (optional) screenshots or files (images, a diagnostics .zip,
//              logs…), up to 5 MB in total.
// A hidden "website" field is a honeypot: a filled one is a bot, answered 200
// and dropped.
//
// What happens to a report:
//   - any uploaded files go to R2 (binding SUPPORT_BUCKET) under
//     support/<id>/<n>-<name>;
//   - the fields go to D1 (binding DB, the same osmium-downloads database), table
//     support_requests (website/analytics/04_support.sql);
//   - a short notice is emailed to support@osmiumsound.it via Resend
//     (secret RESEND_API_KEY), best-effort — if the key is missing or the send
//     fails, the report is already stored, so the request still succeeds.
// No IP address or user-agent is stored, to match the site's aggregate-only
// analytics.
//
// Setup, once (Cloudflare dashboard → Pages project osmium-sound → Settings →
// Bindings, since the site deploys with `wrangler pages deploy`):
//   - R2 bucket binding SUPPORT_BUCKET → bucket osmium-support
//       (npx wrangler r2 bucket create osmium-support);
//   - D1 binding DB → osmium-downloads (already present);
//   - Resend for the notice (keeps the mailbox on Zimbra, no MX change):
//       verify osmiumsound.it in Resend — its DNS records sit on the "send."
//       subdomain and on resend._domainkey, so the apex MX (Zimbra) is left
//       alone — then set the secret RESEND_API_KEY (a sending key scoped to
//       the domain) on the Pages project. Without it the form still works
//       (no email). The notice is sent from NOTIFY_FROM; the reporter's address
//       is the Reply-To and the display name, so a plain reply reaches them.

const MAX_TOTAL = 5 * 1024 * 1024;       // 5 MB of attachments in total, matches the client
const MAX_BODY = MAX_TOTAL + 256 * 1024; // attachments + room for the text fields
const MAX_FILES = 8;                     // at most this many attachments per report
// Attachment types we accept (extension allowlist, mirrored on the client).
const ALLOWED_EXT = new Set([
  "zip", "png", "jpg", "jpeg", "gif", "webp", "pdf", "txt", "log", "json", "csv",
]);
const CONTENT_TYPE = {
  zip: "application/zip", png: "image/png", jpg: "image/jpeg", jpeg: "image/jpeg",
  gif: "image/gif", webp: "image/webp", pdf: "application/pdf", txt: "text/plain",
  log: "text/plain", json: "application/json", csv: "text/csv",
};
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
  notified   INTEGER NOT NULL DEFAULT 0,
  files      TEXT NOT NULL DEFAULT '[]'
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

function extOf(name) {
  const m = /\.([a-z0-9]+)$/i.exec(name || "");
  return m ? m[1].toLowerCase() : "";
}

// Keep the basename, drop anything but safe characters, cap the length.
function safeName(name) {
  const base = String(name || "file").split(/[\\/]/).pop();
  const cleaned = base.replace(/[^A-Za-z0-9._-]+/g, "_").replace(/^_+|_+$/g, "");
  return cleaned.slice(0, 80) || "file";
}

async function notify(env, rec) {
  if (!env.RESEND_API_KEY) return false;
  const line = (k, v) => `${k}: ${v}`;
  const files = rec.files || [];
  const attachLine = files.length
    ? `${files.length} — ` + files.map((f) => `${f.key} (${f.size} B)`).join(", ")
    : "none";
  const text = [
    line("Reference", rec.id),
    line("PC model", rec.model),
    line("Reply to", rec.email || "(not given)"),
    line("Attachments", attachLine),
    "",
    "Problem:",
    rec.problem,
  ].join("\n");
  // Send from our own domain (NOTIFY_FROM); the reporter's address is the
  // display name and the Reply-To, so the support inbox reads as if they wrote
  // and a plain reply reaches them. Resend needs the `from` domain verified.
  const fromName = rec.email.replace(/["\\\r\n]/g, "");
  try {
    const resp = await fetch("https://api.resend.com/emails", {
      method: "POST",
      headers: {
        authorization: `Bearer ${env.RESEND_API_KEY}`,
        "content-type": "application/json",
      },
      body: JSON.stringify({
        from: `"${fromName}" <${NOTIFY_FROM}>`,
        to: [NOTIFY_TO],
        reply_to: rec.email,
        subject: `Support report ${rec.id} — ${rec.model}`.slice(0, 180),
        text,
      }),
    });
    if (!resp.ok) {
      console.error("support notify:", resp.status, (await resp.text()).slice(0, 200));
      return false;
    }
    return true;
  } catch (err) {
    console.error("support notify:", err?.message || err);
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

  // The attachments come from a `multiple` file input named "files".
  const uploads = form.getAll("files").filter((f) => f && typeof f === "object" && f.size > 0);
  if (uploads.length > MAX_FILES) return json(400, { ok: false, error: "too many files" });
  let totalSize = 0;
  for (const f of uploads) {
    if (!ALLOWED_EXT.has(extOf(f.name))) return json(400, { ok: false, error: "file type not allowed" });
    totalSize += f.size;
  }
  if (totalSize > MAX_TOTAL) return json(413, { ok: false, error: "attachments too large" });

  const prefix = uploads.length ? `support/${id}/` : "";
  const stored = [];
  for (let i = 0; i < uploads.length; i++) {
    const f = uploads[i];
    const name = safeName(f.name);
    const key = `${prefix}${i + 1}-${name}`;
    try {
      await env.SUPPORT_BUCKET.put(key, f.stream(), {
        httpMetadata: { contentType: CONTENT_TYPE[extOf(name)] || "application/octet-stream" },
        customMetadata: { id },
      });
    } catch (err) {
      console.error("support r2 put:", err?.message || err);
      return json(500, { ok: false, error: "storage" });
    }
    stored.push({ name, key, size: f.size });
  }

  const rec = { id, model, problem, email, files: stored };
  const notified = await notify(env, rec);

  // Create the table, and add the `files` column on databases made before it
  // existed; both throw harmlessly when already up to date.
  try { await env.DB.prepare(SCHEMA).run(); } catch (_) { /* table exists */ }
  try {
    await env.DB.prepare(`ALTER TABLE support_requests ADD COLUMN files TEXT NOT NULL DEFAULT '[]'`).run();
  } catch (_) { /* column exists */ }

  try {
    await env.DB.prepare(
      `INSERT INTO support_requests (id, created_at, model, problem, email, r2_key, size, notified, files)
       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)`
    ).bind(id, Date.now(), model, problem, email, prefix, totalSize, notified ? 1 : 0, JSON.stringify(stored)).run();
  } catch (err) {
    console.error("support d1 insert:", err?.message || err);
    // The files (if any) are already in R2 and, if configured, the notice was
    // emailed — so the report is not lost. Report success to the visitor.
    return json(200, { ok: true, id });
  }

  return json(200, { ok: true, id });
}
