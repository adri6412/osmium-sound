# HIFI STREAMER — Manuale di montaggio

Scocca in lamiera di alluminio piegata · 5 pezzi + minuteria
Tempo stimato: **30–40 min** · 1 persona · Nessun utensile elettrico richiesto

Prima di iniziare, verifica il contenuto del pacco (§ A) e la minuteria (§ B).
Se manca un pezzo, non forzare il montaggio: rileggi lo Step corrispondente.

---

## A — Pezzi

```
  A            B            C            D            E
┌──────┐   ┌──────┐    ┌────────┐   ┌────────┐   ┌──────────┐
│      │   │//////│    │  ___   │   │ o    o │   │  ┌────┐  │
│  U   │   │//////│    │ | o |  │   │  ┌──┐  │   │  │    │  │
│      │   │//////│    │ |___| ○│   │  └──┘  │   │  └────┘  │
│      │   │//////│    │  [==]  │   │ o    o │   │          │
└──────┘   └──────┘    └────────┘   └────────┘   └──────────┘
 CORPO      COPERCHIO    FRONTALE      RETRO        RIPIANO
 x1          x1           x1           x1            x1
```

| # | Nome | File | Note |
|---|------|------|------|
| **A** | Corpo | `streamer-body.step` | fondo + 2 fianchi, nessun risvolto |
| **B** | Coperchio | `streamer-lid.step` | piatto, con feritoie di ventilazione |
| **C** | Frontale | `streamer-front.step` | piatto — finestra schermo + fessura CD |
| **D** | Retro | `streamer-back.step` | piatto — fori USB / DC / RJ45 |
| **E** | Ripiano | `streamer-shelf.step` | solo nella metà anteriore del Corpo |

**Nota:** C e D sono pannelli **piatti** (nessuna piega) — si tengono in posizione
con le squadrette **③**, non incastrandoli nel Corpo.

---

## B — Minuteria

```
  ①            ②             ③              ④             ⑤              ⑥
  ┃          ╱────╲         ┌─┐             ⊚            ▭▭             ┊┊┊
  ┃  M3       ╲────╱        │ └─┐          M3            USB/RJ45      M3 x168
 24mm      rondella Ø5.5     L 15x15        rondella      (viti proprie) barra filettata
```

| # | Nome | Q.tà | Usato in |
|---|------|------|----------|
| **①a** | Vite M3×10 **a macchina** (testa cilindrica/bombata) | **4** | schermo: attraversa rondella larga + foro Ø5.5 e si serra con dado **⑦** dietro la scheda |
| **①b** | Vite M3×8 autofilettante | **20** | squadrette front/back→fianchi (16), ripiano→fianchi (4) |
| **②** | Squadretta a L (staffa 15×15×1.5 mm, meglio con fori ad asola) | **8** | fissaggio D↔A (6, 3 livelli per lato) + C↔A (2, **solo livello basso** — vedi nota) |
| **③** | Rondella M3 | **16** | schermo (4, **larghe** Ø9–12 per coprire il foro Ø5.5) + tiranti fondo↔coperchio (12, 2 per tirante) |
| **④** | Dado passante (jack DC) | **1** | fissaggio jack barrel DC-022 |
| **⑤** | Viti proprie dei connettori | — | incluse con USB-A doppia e RJ45 panel-mount |
| **⑥** | Barra filettata M3 Ø3mm, tagliata a ~168 mm | **6** | tiranti che tengono insieme Corpo (A) e Coperchio (B) — niente più risvolti |
| **⑦** | Dado M3 | **16** | 2 per tirante (12) + 4 dietro la scheda dello schermo |

> ⚠ **Squadrette del Frontale — solo livello basso.** I fori a metà e in alto
> (z ≈ 86 / 142 mm) cadono **dietro il modulo schermo** (che copre la fascia
> z ≈ 38–162 mm): lì non c'è spazio né per la squadretta né per la testa della vite.
> Sul Frontale monta solo le 2 squadrette basse; i fori centrali e alti del frontale
> e dei fianchi lato front restano inutilizzati. Sul Retro tutti e 3 i livelli sono ok.

Componenti da procurarsi a parte (non inclusi nella scocca):
schermo Waveshare 7" (C) Rev2.1 · lettore CD slim USB · mini PC BMAX N100 ·
biadesivo forte per CD e mini PC.

---

## Attrezzi necessari

```
   ✚              ⬡
 cacciavite     (facoltativo:
 a croce PH1     chiave a brugola
                 se usi inserti)
```

---

## ⚠ Prima di iniziare

- Non stringere le viti a fondo finché non hai chiuso **tutta** la scocca (Step 1-6):
  lascia gioco per correggere gli allineamenti, stringi tutto solo all'ultimo Step.
- I fori schermo (Ø5.5) hanno **±1 mm** di tolleranza: è normale un piccolo gioco.

---

## Step 1 — Schermo → Frontale (C)

```
        C (retro pannello)
   ┌───────────────────────┐
   │  ○               ○    │
   │      ┌─────────┐      │   ○ = 4 fori Ø5.5
   │      │ SCHERMO │      │   interasse 156 × 115 (reale, misurato)
   │      └─────────┘      │
   │  ○               ○    │
   └───────────────────────┘
```

1. Appoggia lo **schermo** dietro al pannello **C**, area visibile centrata nella finestra.
2. Allinea i 4 fori scheda ai 4 fori Ø5.5 del pannello.
3. Fissa con **①a×4 + ③×4 + ⑦×4**: vite + rondella larga dal davanti,
   dado **⑦** serrato dietro la scheda (la vite NON fa presa nel pannello:
   il foro Ø5.5 è maggiorato apposta per dare ±1 mm di gioco).

`①a ×4  ③ ×4  ⑦ ×4`

> ⚠ **Pezzi del lotto 1** (prodotti con interasse 152.1 × 113.1): l'interasse reale
> dei fori dello schermo è **156 × 115** → prima di montare, allarga a lima i 4 fori
> del frontale di ~2 mm verso l'esterno in orizzontale (e ~1 mm in verticale).
> Le rondelle larghe coprono l'occhiello. Il CAD è già stato corretto per i lotti futuri.

---

## Step 2 — Connettori → Retro (D)

```
        D (esterno pannello)
   ┌───────────────────────┐
   │  [USB][USB]  ◯   [══] │
   │                        │
   └───────────────────────┘
       USB-A x2      DC    RJ45
```

1. Monta la **doppia USB-A** (interasse 28 mm) con le sue viti.
2. Monta il **jack DC** nel foro da 8 mm, fissalo con il dado **④**.
3. Monta il **RJ45** (interasse 27.1 mm) con le sue viti.

`⑤ (viti proprie) + ④ ×1`

---

## Step 3 — Lettore CD → Corpo (A)

```
   ┌─────────────────────────┐
   │                         │
   │     [ CD READER ]  ▭▭▭▭ │  ← incollato sul fondo,
   │                         │     cassetto verso la fessura
   └─────────────────────────┘
```

1. Incolla il **lettore CD** sul fondo del Corpo **A** con biadesivo.
2. Allinea il cassetto con la fessura del pannello **C** (verificalo tenendo **C** accostato,
   senza ancora avvitarlo).

*(nessuna vite — solo biadesivo)*

---

## Step 4 — Ripiano (E) → Corpo (A)

```
        fianco sx A        E (ripiano)        fianco dx A
        │  o           ┌──────────────┐          o  │
        │  o  ←──────  │   MINI PC    │  ──────→ o  │
        │              └──────────────┘             │
```

1. Inserisci le alette del ripiano **E** contro l'interno dei fianchi di **A**.
2. Avvita **①b ×2 per lato** (4 totali), viti orizzontali dall'esterno dei fianchi.
3. Incolla il **mini PC** su **E** con biadesivo, verso il lato anteriore (lascia liberi
   i ~70 mm posteriori per i cavi).

`①b ×4`

---

## Step 5 — Cablaggio (prima di chiudere!)

```
   SCHERMO ──HDMI/USB──► PC ◄──USB── CD READER
                          │
                   rete / USB / DC
                          │
                          ▼
                       RETRO (D)
```

1. Collega **schermo → mini PC** (HDMI + USB touch/alimentazione).
2. Collega **lettore CD → mini PC** (USB).
3. Porta i cavi dei connettori di **D** alle rispettive porte del PC.

*(nessuna vite in questo step — è l'ultimo momento comodo per i cavi)*

---

## Step 6 — Frontale (C) e Retro (D) → Corpo (A)

```
        squadretta ② vista di profilo:

        fianco A          pannello C/D
           │╲                  │
           │ ╲___②___          │
           │      \___①b______ │
           │                   │
          vite ①b(orizz. larg.)  vite ①b(orizz. prof.)
```

1. **Frontale (C)**: inserisci **1 squadretta ②** per fianco, **solo al livello basso**
   (⚠ a metà e in alto c'è lo schermo: quei fori restano vuoti).
   Accosta **C** e avvita **①b ×2** dal pannello + **①b ×2** dai fianchi.
2. **Retro (D)**: inserisci **3 squadrette ②** per fianco (basso / metà / alto).
   Accosta **D** e avvita **①b ×6** dal pannello + **①b ×6** dai fianchi.

`①b ×16  (4 per C, 12 per D)   ② ×8`

> Non stringere ancora a fondo: prosegui allo Step 7, poi torna a serrare tutto.

---

## Step 7 — Tiranti: Coperchio (B) ↔ Corpo (A)

```
   vista dall'alto del fondo/coperchio — 6 tiranti alle stesse X/Y:

   ┌───────────────────────────────┐
   │  ⑥            ⑥            ⑥  │   x = 30 / 90.45 / 150.9 mm
   │                                 │
   │  ⑥            ⑥            ⑥  │
   └───────────────────────────────┘
```

> Il Coperchio **non si avvita ai fianchi** (A non ha più risvolti): B e A restano
> uniti da **6 tiranti filettati M3** verticali, che passano nell'interno della scocca
> allineati (stessa X/Y sopra e sotto).

1. Avvita **⑦ dado + ③ rondella** su un'estremità di ogni tirante **⑥**.
2. Infila i 6 tiranti nei fori del **fondo** (dall'esterno, sotto il Corpo **A**).
3. Appoggia il **Coperchio (B)** sopra, facendo passare i tiranti nei 6 fori corrispondenti
   (stessa griglia X/Y del fondo).
4. Blocca ogni tirante dall'alto con **③ rondella + ⑦ dado**, serrando A e B tra loro.

`⑥ ×6  ⑦ ×12  ③ ×12`

---

## Step 8 — Serraggio finale

1. Ricontrolla l'allineamento di schermo, fessura CD e connettori posteriori.
2. Stringi **tutto** in ordine: Frontale/Retro (Step 6) → Tiranti (Step 7)
   → Ripiano (Step 4) → Schermo (Step 1).

**Fatto — la scocca è chiusa.** ✔

---

## Riepilogo minuteria per step

| Step | ①a M3×10 | ①b M3×8 | ② Squadretta | ③ Rondella | ④ Dado (DC) | ⑥ Tirante | ⑦ Dado M3 |
|---|---|---|---|---|---|---|---|
| 1 — Schermo | 4 | — | — | 4 | — | — | 4 |
| 2 — Connettori | — | (proprie) | — | — | 1 | — | — |
| 4 — Ripiano | — | 4 | — | — | — | — | — |
| 6 — Frontale/Retro | — | 16 | 8 | — | — | — | — |
| 7 — Tiranti | — | — | — | 12 | — | 6 | 12 |
| **Totale** | **4** | **20** | **8** | **16** | **1** | **6** | **16** |
