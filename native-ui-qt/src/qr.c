#include "qr.h"
#include <string.h>
#ifdef QR_DEBUG
#include <stdio.h>
#endif

// ─── aritmetica in GF(256) per Reed-Solomon ────────────────────────────────
// Polinomio generatore del campo: 0x11D, come da specifica QR.
static unsigned char gf_exp[512], gf_log[256];
static bool gf_ready;

static void gf_init(void) {
    if (gf_ready) return;
    int x = 1;
    for (int i = 0; i < 255; i++) {
        gf_exp[i] = (unsigned char)x;
        gf_log[x] = (unsigned char)i;
        x <<= 1;
        if (x & 0x100) x ^= 0x11D;
    }
    for (int i = 255; i < 512; i++) gf_exp[i] = gf_exp[i - 255];
    gf_ready = true;
}
static unsigned char gf_mul(unsigned char a, unsigned char b) {
    if (!a || !b) return 0;
    return gf_exp[gf_log[a] + gf_log[b]];
}

// Calcola i `ec` codeword di correzione per `data`.
static void rs_encode(const unsigned char *data, int n, int ec, unsigned char *out) {
    unsigned char gen[70];
    memset(gen, 0, sizeof gen);
    gen[0] = 1;
    int glen = 1;
    for (int i = 0; i < ec; i++) {                 // (x - a^0)(x - a^1)...
        gen[glen] = 0;
        glen++;
        for (int j = glen - 1; j > 0; j--)
            gen[j] = gen[j - 1] ^ gf_mul(gen[j], gf_exp[i]);
        gen[0] = gf_mul(gen[0], gf_exp[i]);
    }
    memset(out, 0, (size_t)ec);
    for (int i = 0; i < n; i++) {
        unsigned char f = data[i] ^ out[0];
        memmove(out, out + 1, (size_t)ec - 1);
        out[ec - 1] = 0;
        // gen[] e' in ordine crescente (gen[0] costante, gen[ec] guida): qui
        // servono i coefficienti in ordine decrescente ESCLUSO quello guida,
        // cioe' gen[ec-1] .. gen[0].
        if (f) for (int j = 0; j < ec; j++) out[j] ^= gf_mul(gen[ec - 1 - j], f);
    }
}

// ─── tabelle di correzione, versioni 1..20, tutti e quattro i livelli ──────
// `qrcode.react` (cioe' qrcodegen) ALZA il livello di correzione al massimo
// che entra nella versione scelta, senza cambiare versione — quindi per
// ottenere lo stesso disegno bisogna farlo anche qui.
// Per ogni voce: codeword di correzione per blocco, blocchi del gruppo 1,
// blocchi del gruppo 2 (che hanno un codeword dato in piu').
typedef struct { short ecpb, g1, g2; } ecspec_t;

static const short TOTAL[21] = {
    0, 26, 44, 70, 100, 134, 172, 196, 242, 292, 346,
    404, 466, 532, 581, 655, 733, 815, 901, 991, 1085,
};

// ordine: L, M, Q, H (come i due bit del formato: 01, 00, 11, 10)
static const ecspec_t ECC[4][21] = {
    {   // L
        {0,0,0},
        { 7,1,0},{10,1,0},{15,1,0},{20,1,0},{26,1,0},{18,2,0},{20,2,0},
        {24,2,0},{30,2,0},{18,2,2},{20,4,0},{24,2,2},{26,4,0},{30,3,1},
        {22,5,1},{24,5,1},{28,1,5},{30,5,1},{28,3,4},{28,3,5},
    },
    {   // M
        {0,0,0},
        {10,1,0},{16,1,0},{26,1,0},{18,2,0},{24,2,0},{16,4,0},{18,4,0},
        {22,2,2},{22,3,2},{26,4,1},{30,1,4},{22,6,2},{22,8,1},{24,4,5},
        {24,5,5},{28,7,3},{28,10,1},{26,9,4},{26,3,11},{26,3,13},
    },
    {   // Q
        {0,0,0},
        {13,1,0},{22,1,0},{18,2,0},{26,2,0},{18,2,2},{24,4,0},{18,2,4},
        {22,4,2},{20,4,4},{24,6,2},{28,4,4},{26,4,6},{24,8,4},{20,11,5},
        {30,5,7},{24,15,2},{28,1,15},{28,17,1},{26,17,4},{30,15,5},
    },
    {   // H
        {0,0,0},
        {17,1,0},{28,1,0},{22,2,0},{16,4,0},{22,2,2},{28,4,0},{26,4,1},
        {26,4,2},{24,4,4},{28,6,2},{24,3,8},{28,7,4},{22,12,4},{24,11,5},
        {24,11,7},{30,3,13},{28,2,17},{28,2,19},{26,9,16},{28,15,10},
    },
};
// bit del livello nelle informazioni di formato
static const int LEVEL_BITS[4] = {1, 0, 3, 2};

// Centri dei pattern di allineamento per versione (0 = fine elenco).
static const unsigned char ALIGN[21][7] = {
    {0}, {0}, {6,18,0}, {6,22,0}, {6,26,0}, {6,30,0}, {6,34,0},
    {6,22,38,0}, {6,24,42,0}, {6,26,46,0}, {6,28,50,0}, {6,30,54,0},
    {6,32,58,0}, {6,34,62,0}, {6,26,46,66,0}, {6,26,48,70,0}, {6,26,50,74,0},
    {6,30,54,78,0}, {6,30,56,82,0}, {6,30,58,86,0}, {6,34,62,90,0},
};

static int data_codewords(int lvl, int v) {
    const ecspec_t *e = &ECC[lvl][v];
    return TOTAL[v] - e->ecpb * (e->g1 + e->g2);
}

// ─── matrice ───────────────────────────────────────────────────────────────
static unsigned char fixed[QR_MAX_SIZE][QR_MAX_SIZE];   // 1 = modulo di funzione

static void put(qr_t *q, int x, int y, int dark, int is_fixed) {
    if (x < 0 || y < 0 || x >= q->size || y >= q->size) return;
    q->m[y][x] = (unsigned char)(dark != 0);
    fixed[y][x] = (unsigned char)is_fixed;
}

static void finder(qr_t *q, int ox, int oy) {
    for (int dy = -1; dy <= 7; dy++)
        for (int dx = -1; dx <= 7; dx++) {
            int x = ox + dx, y = oy + dy;
            if (x < 0 || y < 0 || x >= q->size || y >= q->size) continue;
            int in = dx >= 0 && dx <= 6 && dy >= 0 && dy <= 6;
            int ring = in && (dx == 0 || dx == 6 || dy == 0 || dy == 6);
            int core = in && dx >= 2 && dx <= 4 && dy >= 2 && dy <= 4;
            put(q, x, y, ring || core, 1);
        }
}

static void alignment(qr_t *q, int v) {
    const unsigned char *a = ALIGN[v];
    for (int i = 0; a[i]; i++)
        for (int j = 0; a[j]; j++) {
            int cx = a[i], cy = a[j];
            // non sopra i tre pattern di ricerca
            if ((cx <= 8 && cy <= 8) || (cx <= 8 && cy >= q->size - 9) ||
                (cx >= q->size - 9 && cy <= 8)) continue;
            for (int dy = -2; dy <= 2; dy++)
                for (int dx = -2; dx <= 2; dx++) {
                    int edge = dx == -2 || dx == 2 || dy == -2 || dy == 2;
                    put(q, cx + dx, cy + dy, edge || (dx == 0 && dy == 0), 1);
                }
        }
}

// Informazioni di formato: 5 bit (livello + maschera) con BCH(15,5).
static void format_info(qr_t *q, int lvl, int mask) {
    int data = (LEVEL_BITS[lvl] << 3) | mask;
    int v = data << 10;
    for (int i = 4; i >= 0; i--)
        if (v & (1 << (i + 10))) v ^= 0x537 << i;
    int bits = ((data << 10) | v) ^ 0x5412;
    for (int i = 0; i < 15; i++) {
        int b = (bits >> i) & 1;
        if (i < 6)       put(q, 8, i, b, 1);
        else if (i < 8)  put(q, 8, i + 1, b, 1);
        else if (i == 8) put(q, 7, 8, b, 1);
        else             put(q, 14 - i, 8, b, 1);

        if (i < 8) put(q, q->size - 1 - i, 8, b, 1);
        else       put(q, 8, q->size - 15 + i, b, 1);
    }
    put(q, 8, q->size - 8, 1, 1);            // modulo scuro, sempre
}

// Informazioni di versione (solo dalla 7 in su): BCH(18,6).
static void version_info(qr_t *q, int ver) {
    if (ver < 7) return;
    int v = ver << 12;
    for (int i = 5; i >= 0; i--)
        if (v & (1 << (i + 12))) v ^= 0x1F25 << i;
    int bits = (ver << 12) | v;
    for (int i = 0; i < 18; i++) {
        int b = (bits >> i) & 1;
        put(q, i / 3, q->size - 11 + i % 3, b, 1);
        put(q, q->size - 11 + i % 3, i / 3, b, 1);
    }
}

static int mask_bit(int mask, int x, int y) {
    switch (mask) {
    case 0: return (y + x) % 2 == 0;
    case 1: return y % 2 == 0;
    case 2: return x % 3 == 0;
    case 3: return (y + x) % 3 == 0;
    case 4: return (y / 2 + x / 3) % 2 == 0;
    case 5: return (y * x) % 2 + (y * x) % 3 == 0;
    case 6: return ((y * x) % 2 + (y * x) % 3) % 2 == 0;
    default: return ((y + x) % 2 + (y * x) % 3) % 2 == 0;
    }
}

// Punteggio di penalita' della specifica, per scegliere la maschera migliore.
// Punteggio di penalita'. E' quello di qrcodegen (la libreria dietro
// `qrcode.react`), non la lettura ingenua della specifica: la differenza sta
// in N3, dove il bordo del simbolo conta come modulo chiaro, e in N4, dove la
// formula e' a gradini interi. Senza queste due sottigliezze la maschera
// scelta cambia e il disegno non coincide con quello della UI Electron.
static int fp_count(const int *rh) {
    int n = rh[1];
    int core = n > 0 && rh[2] == n && rh[3] == n * 3 && rh[4] == n && rh[5] == n;
    return (core && rh[0] >= n * 4 && rh[6] >= n ? 1 : 0)
         + (core && rh[6] >= n * 4 && rh[0] >= n ? 1 : 0);
}
static void fp_add(int run, int *rh, int size) {
    if (rh[0] == 0) run += size;              // bordo chiaro virtuale a inizio linea
    for (int i = 6; i > 0; i--) rh[i] = rh[i - 1];
    rh[0] = run;
}
static int fp_end(int color, int run, int *rh, int size) {
    if (color) { fp_add(run, rh, size); run = 0; }
    run += size;                               // bordo chiaro virtuale a fine linea
    fp_add(run, rh, size);
    return fp_count(rh);
}

static int penalty(const qr_t *q) {
    const int N1 = 3, N2 = 3, N3 = 40, N4 = 10;
    int n = q->size, p = 0;

    for (int y = 0; y < n; y++) {              // righe: N1 e N3
        int rh[7] = {0}, color = 0, run = 0;
        for (int x = 0; x < n; x++) {
            if (q->m[y][x] == color) {
                run++;
                if (run == 5) p += N1;
                else if (run > 5) p++;
            } else {
                fp_add(run, rh, n);
                if (!color) p += fp_count(rh) * N3;
                color = q->m[y][x];
                run = 1;
            }
        }
        p += fp_end(color, run, rh, n) * N3;
    }
    for (int x = 0; x < n; x++) {              // colonne: idem
        int rh[7] = {0}, color = 0, run = 0;
        for (int y = 0; y < n; y++) {
            if (q->m[y][x] == color) {
                run++;
                if (run == 5) p += N1;
                else if (run > 5) p++;
            } else {
                fp_add(run, rh, n);
                if (!color) p += fp_count(rh) * N3;
                color = q->m[y][x];
                run = 1;
            }
        }
        p += fp_end(color, run, rh, n) * N3;
    }

    for (int y = 0; y + 1 < n; y++)            // N2: blocchi 2x2
        for (int x = 0; x + 1 < n; x++)
            if (q->m[y][x] == q->m[y][x + 1] && q->m[y][x] == q->m[y + 1][x] &&
                q->m[y][x] == q->m[y + 1][x + 1]) p += N2;

    int dark = 0, total = n * n;               // N4: sbilanciamento
    for (int y = 0; y < n; y++) for (int x = 0; x < n; x++) dark += q->m[y][x];
    int d = dark * 20 - total * 10;
    if (d < 0) d = -d;
    int k = (d + total - 1) / total - 1;
    p += k * N4;
    return p;
}

bool qr_encode(qr_t *q, const unsigned char *data, size_t len) {
    return qr_encode_mask(q, data, len, -1);
}

bool qr_encode_mask(qr_t *q, const unsigned char *data, size_t len, int force) {
    gf_init();

    // 1. versione minima che contiene i dati al livello M (modo byte)...
    int ver = 0, lvl = 1;                          // 1 = M
    for (int v = 1; v <= 20; v++) {
        int hdr = 4 + (v < 10 ? 8 : 16);
        if ((int)len * 8 + hdr <= data_codewords(1, v) * 8) { ver = v; break; }
    }
    if (!ver) return false;
    // ...e poi il livello piu' alto che entra ancora in QUELLA versione, che e'
    // quello che fa qrcodegen con boostEcl: piu' correzione allo stesso prezzo.
    {
        int hdr = 4 + (ver < 10 ? 8 : 16);
        int need = (int)len * 8 + hdr;
        if (need <= data_codewords(3, ver) * 8) lvl = 3;        // H
        else if (need <= data_codewords(2, ver) * 8) lvl = 2;   // Q
    }

    int ncw = data_codewords(lvl, ver);
    unsigned char buf[1200];
    memset(buf, 0, sizeof buf);

    // 2. flusso di bit: modo 0100, conteggio, dati, terminatore, riempimento
    int bit = 0;
    #define PUTBITS(val, n) do {                                            \
        for (int _i = (n) - 1; _i >= 0; _i--) {                              \
            if ((val) & (1 << _i))                                           \
                buf[bit >> 3] |= (unsigned char)(0x80 >> (bit & 7));         \
            bit++;                                                           \
        }                                                                    \
    } while (0)
    PUTBITS(4, 4);
    PUTBITS((int)len, ver < 10 ? 8 : 16);
    for (size_t i = 0; i < len; i++) PUTBITS(data[i], 8);
    for (int i = 0; i < 4 && bit < ncw * 8; i++) bit++;      // terminatore
    while (bit & 7) bit++;                                   // a byte pieno
    for (int i = bit >> 3, alt = 0; i < ncw; i++, alt ^= 1) buf[i] = alt ? 0x11 : 0xEC;
    #undef PUTBITS

    // 3. blocchi, correzione, interlacciamento
    int g1 = ECC[lvl][ver].g1, g2 = ECC[lvl][ver].g2, ec = ECC[lvl][ver].ecpb;
    int nblk = g1 + g2;
    int d1 = ncw / nblk, d2 = d1 + 1;
    unsigned char dat[50][160], ecc[50][70];
    int dlen[50];
    const unsigned char *p = buf;
    for (int b = 0; b < nblk; b++) {
        dlen[b] = b < g1 ? d1 : d2;
        memcpy(dat[b], p, (size_t)dlen[b]);
        p += dlen[b];
        rs_encode(dat[b], dlen[b], ec, ecc[b]);
    }
    unsigned char stream[3000];
    int sn = 0;
    for (int i = 0; i < d2; i++)
        for (int b = 0; b < nblk; b++)
            if (i < dlen[b]) stream[sn++] = dat[b][i];
    for (int i = 0; i < ec; i++)
        for (int b = 0; b < nblk; b++) stream[sn++] = ecc[b][i];

#ifdef QR_DEBUG
    fprintf(stderr, "ver=%d lvl=%d ncw=%d nblk=%d ec=%d stream:", ver, lvl, ncw, nblk, ec);
    for (int i = 0; i < sn; i++) fprintf(stderr, " %02X", stream[i]);
    fprintf(stderr, "\n");
#endif

    // 4. matrice: pattern fissi, poi i dati a zig-zag
    q->size = 17 + 4 * ver;
    memset(q->m, 0, sizeof q->m);
    memset(fixed, 0, sizeof fixed);
    finder(q, 0, 0);
    finder(q, q->size - 7, 0);
    finder(q, 0, q->size - 7);
    alignment(q, ver);
    for (int i = 8; i < q->size - 8; i++) {           // pattern di sincronismo
        put(q, i, 6, (i % 2) == 0, 1);
        put(q, 6, i, (i % 2) == 0, 1);
    }
    format_info(q, lvl, 0);                            // riservati, poi riscritti
    version_info(q, ver);

    int idx = 0, bitpos = 0, dir = -1, y = q->size - 1;
    for (int x = q->size - 1; x > 0; x -= 2) {
        if (x == 6) x--;                               // salta la colonna di sincronismo
        while (y >= 0 && y < q->size) {
            for (int k = 0; k < 2; k++) {
                int xx = x - k;
                if (fixed[y][xx]) continue;
                int b = 0;
                if (idx < sn) b = (stream[idx] >> (7 - bitpos)) & 1;
                if (++bitpos == 8) { bitpos = 0; idx++; }
                q->m[y][xx] = (unsigned char)b;
            }
            y += dir;
        }
        dir = -dir;
        y += dir;
    }

    // 5. maschera migliore fra le otto
    qr_t best;
    int best_p = -1;
    for (int mask = force >= 0 ? force : 0; mask < (force >= 0 ? force + 1 : 8); mask++) {
        qr_t t = *q;
        for (int yy = 0; yy < t.size; yy++)
            for (int xx = 0; xx < t.size; xx++)
                if (!fixed[yy][xx] && mask_bit(mask, xx, yy)) t.m[yy][xx] ^= 1;
        format_info(&t, lvl, mask);
        int pen = penalty(&t);
#ifdef QR_DEBUG
        fprintf(stderr, "maschera %d penalita' %d\n", mask, pen);
#endif
        if (best_p < 0 || pen < best_p) { best_p = pen; best = t; }
    }
    *q = best;
    return true;
}
