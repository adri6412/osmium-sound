// qr — generatore di codici QR, modo byte, correzione M.
//
// Gli stessi parametri della UI Electron, che usa `qrcode.react` con
// `level="M"` e 200 px di lato (Settings.jsx:3491): stesso contenuto, stessa
// densita' di moduli, quindi la stessa inquadratura funziona con le app.
//
// Copre le versioni 1..20 (fino a 666 byte in M), piu' che sufficienti per il
// JSON di abbinamento del companion e per gli URL.
//
// Solo modo byte, come qrcodegen quando la stringa non e' interamente numerica
// o alfanumerica — cioe' sempre, per URL e JSON (hanno minuscole e simboli).
// Come qrcodegen, il livello di correzione viene ALZATO al massimo che entra
// nella versione scelta, cosi' il disegno coincide con quello di Electron.
//
// Verificato: 9 payload reali su 9 (URL App Store, JSON di abbinamento, testo
// accentato, versioni 3..18) danno una matrice IDENTICA a `qrcode.react`.
#ifndef QR_H
#define QR_H

#include <stdbool.h>
#include <stddef.h>

#define QR_MAX_SIZE 97          // versione 20: 17 + 4*20 moduli per lato

typedef struct {
    int  size;                  // lato in moduli
    unsigned char m[QR_MAX_SIZE][QR_MAX_SIZE];   // 1 = modulo scuro
} qr_t;

// Codifica `data` (lunghezza `len`) nel QR. false se non ci sta.
bool qr_encode(qr_t *q, const unsigned char *data, size_t len);
// Come sopra ma con una maschera imposta (0..7); `mask` < 0 = scelta
// automatica. Serve a confrontare l'uscita con quella di qrcode.react.
bool qr_encode_mask(qr_t *q, const unsigned char *data, size_t len, int mask);

#endif
