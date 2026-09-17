// HyperLogLog: counts distinct visitors without keeping a row, or anything
// else, about any of them. A sketch is 4096 one-byte registers (4 KB) stored
// as a D1 BLOB; adding a visitor only ever raises one register, so the sketch
// cannot be walked back to the hashes that built it.
//
// Sketches merge by taking the larger of each pair of registers, which is why
// unique visitors for a month or a year are the union of the daily sketches:
// nothing raw has to be kept to answer that question later.
//
// Standalone on purpose: Workers have no packages at runtime, and the backfill
// script and the tests import this same file. The same file lives in
// osmium-iso-tracker/src/hll.js, which reads these sketches back for the
// dashboard: keep the two copies identical.
//
// Accuracy at 12 bits of precision is about 1.6% on large sets; below the
// canonical 2.5 * m threshold the estimate comes from linear counting instead,
// which on this site's numbers is exact in practice.

const P = 12; // bits of the hash that pick the register
const M = 1 << P; // 4096 registers
const MAX_ZEROS = 32 - P; // the 20 bits left to count leading zeros in
const ALPHA = 0.7213 / (1 + 1.079 / M);
const TWO_32 = 4294967296;
const LINEAR_THRESHOLD = 2.5 * M;

export const REGISTERS = M;

export function empty() {
  return new Uint8Array(M);
}

// Folds one 32-bit hash into the sketch. Returns true when a register actually
// changed, so callers can skip rewriting an unchanged 4 KB blob.
export function add(sketch, hash) {
  const h = hash >>> 0;
  const index = h >>> MAX_ZEROS;
  const rest = (h << P) >>> 0;
  // clz32 on a word whose low 12 bits are zero saturates at 32; cap it at the
  // 20 bits that carry information, so an all-zero remainder ranks 21.
  const rank = Math.min(MAX_ZEROS, Math.clz32(rest)) + 1;
  if (sketch[index] >= rank) return false;
  sketch[index] = rank;
  return true;
}

// Union of two sketches. Associative and commutative, because max is.
export function merge(a, b) {
  const left = deserialize(a);
  const right = deserialize(b);
  const out = new Uint8Array(M);
  for (let i = 0; i < M; i++) out[i] = left[i] > right[i] ? left[i] : right[i];
  return out;
}

export function count(sketch) {
  const registers = deserialize(sketch);
  let sum = 0;
  let zeros = 0;
  for (let i = 0; i < M; i++) {
    const rank = registers[i];
    if (rank === 0) zeros++;
    sum += 2 ** -rank;
  }
  const estimate = (ALPHA * M * M) / sum;
  if (estimate <= LINEAR_THRESHOLD && zeros > 0) {
    return Math.round(M * Math.log(M / zeros));
  }
  if (estimate > TWO_32 / 30) {
    return Math.round(-TWO_32 * Math.log(1 - estimate / TWO_32));
  }
  return Math.round(estimate);
}

// A copy of the registers, ready to bind as a D1 BLOB.
export function serialize(sketch) {
  return Uint8Array.from(deserialize(sketch));
}

// Accepts what D1 hands back for a BLOB across runtimes (ArrayBuffer, a typed
// array or a plain array of bytes) and an absent column, which is an empty
// sketch. A wrong length is corruption and is not quietly restarted from zero.
export function deserialize(value) {
  if (value === null || value === undefined) return empty();
  let bytes;
  if (value instanceof Uint8Array) bytes = value;
  else if (value instanceof ArrayBuffer) bytes = new Uint8Array(value);
  else if (ArrayBuffer.isView(value)) bytes = new Uint8Array(value.buffer, value.byteOffset, value.byteLength);
  else if (Array.isArray(value)) bytes = Uint8Array.from(value);
  else throw new TypeError(`hll: cannot read a sketch from ${typeof value}`);
  if (bytes.length !== M) throw new RangeError(`hll: sketch is ${bytes.length} bytes, expected ${M}`);
  return bytes;
}
