// What the supporters list keeps from a Ko-fi webhook, shared by the
// webhook (api/kofi.js), the list the home page reads (api/supporters.js)
// and tests/test-site-analytics.mjs.

export const MAX_NAMES = 30;
const MAX_NAME_LENGTH = 40;
const MAX_MESSAGE_LENGTH = 300;
const KINDS = new Set(["Donation", "Subscription"]);

// Ko-fi's "Send test" button posts this made-up supporter with the real
// token. It proves the webhook works, and must not end up on the home page.
const TEST_TRANSACTION = "00000000-1111-2222-3333-444444444444";
const TEST_NAME = "Jo Example";

export const SCHEMA = `CREATE TABLE IF NOT EXISTS kofi_supporters (
  message_id TEXT PRIMARY KEY,
  name       TEXT NOT NULL,
  ts         INTEGER NOT NULL,
  message    TEXT NOT NULL DEFAULT ''
)`;

// Control characters and the bidirectional overrides are dropped (text
// that flips the rest of the line around is not a name or a message); emoji
// and every alphabet stay. Whitespace collapses, length is capped.
function cleanText(raw, max) {
  if (typeof raw !== "string") return "";
  const text = raw
    .normalize("NFC")
    .replace(/[\p{Cc}\u200E\u200F\u202A-\u202E\u2066-\u2069]/gu, " ")
    .replace(/\s+/g, " ")
    .trim();
  const chars = [...text];
  return chars.length <= max ? text : chars.slice(0, max - 1).join("").trim() + "…";
}

export const cleanName = (raw) => cleanText(raw, MAX_NAME_LENGTH);
export const cleanMessage = (raw) => cleanText(raw, MAX_MESSAGE_LENGTH);

// What to keep from one Ko-fi payload: { id, name, message } or null. The
// message is the one the supporter wrote on Ko-fi, public there as well.
export function supporterOf(data) {
  if (!data || !KINDS.has(data.type) || data.is_public !== true) return null;
  if (data.kofi_transaction_id === TEST_TRANSACTION) return null;
  const name = cleanName(data.from_name);
  if (!name || name === TEST_NAME) return null;
  const id = typeof data.message_id === "string" ? data.message_id.slice(0, 64) : "";
  return id ? { id, name, message: cleanMessage(data.message) } : null;
}
