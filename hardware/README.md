# Scocca Network Streamer HiFi

> ⚠️ **BETA — non ancora testata.** Il progetto della scocca è in fase di prima
> validazione: i pezzi sono stati prodotti ma il **montaggio completo non è ancora
> stato eseguito**. Misure, fori e istruzioni potrebbero contenere errori non ancora
> emersi. Non ordinare pezzi basandoti su questi file senza una verifica propria.

Cabinet in **lamiera di alluminio piegata** (JLCPCB Sheet Metal) per il network
streamer HiFi, con schermo touch da 7", lettore CD slim e mini PC.

Tutto il progetto è nella cartella [`freecad/`](freecad/): script parametrici FreeCAD
che generano i file STEP da ordinare.

---

## 1. Componenti alloggiati

| Componente | Modello | Ingombro (mm) | Fissaggio |
|---|---|---|---|
| Schermo | Waveshare 7" HDMI LCD (C) Rev2.1 | scheda 164.9 × 124.27 × 15; area visibile 154.21 × 85.92 | 4 viti M3 (interasse **156 × 115**, misurato sul pezzo reale) |
| Lettore CD | slim USB a cassetto frontale | 137.2 × 137.2 × 15 | biadesivo sul fondo |
| Mini PC | BMAX N100 16GB/512GB | 121 × 141.1 × 27.1 | biadesivo sul ripiano |
| Connettori retro | doppia USB-A, jack DC, RJ45 | — | a vite / dado |

---

## 2. La scocca

**Dimensioni esterne: 180.9 (L) × 172.3 (H) × 220.0 (P) mm** — lamiera **Alluminio 5052, 2 mm**.

È composta da **5 pezzi** che si avvitano tra loro:

| Pezzo | File STEP | Descrizione |
|---|---|---|
| Corpo | `streamer-body.step` | profilo a U (fondo + 2 fianchi, nessun risvolto) |
| Frontale | `streamer-front.step` | vaschetta con finestra schermo + fessura CD + 4 fori schermo |
| Retro | `streamer-back.step` | vaschetta con fori USB doppia / DC / RJ45 |
| Coperchio | `streamer-lid.step` | piano con feritoie di ventilazione |
| Ripiano | `streamer-shelf.step` | piano interno (porta mini PC), solo nella metà anteriore |

Layout interno: **lettore CD sul fondo** (dietro la fessura), **mini PC sul ripiano**
sopra il CD. Dietro al PC restano **~70 mm** liberi per connettori e cavi.

---

## 3. File nel progetto (`freecad/`)

```
freecad/
├── streamer_sheetmetal.py   # genera la geometria (corpo + 4 pezzi) -> STEP + STL
├── unfold.py                # sviluppa la lamiera piatta -> DXF (K-factor 0.38)
├── verify.py                # controllo manifatturabilità (solidi, fori, interferenze)
├── silkscreen_dxf.py        # testo "HIFI STREAMER" come contorni -> DXF (laser/serigrafia)
├── silkscreen-front.svg     # stessa scritta in SVG
└── out/
    ├── streamer-assembly.step      # assieme completo (anteprima)
    ├── streamer-{body,front,back,lid,shelf}.step   # i 5 pezzi -> da caricare su JLC
    ├── unfold-*.dxf                # sviluppati piatti (opzionali, JLC sviluppa da solo)
    ├── silkscreen-front.dxf        # scritta per laser marking
    └── *.stl / *.png               # anteprime
```

### Rigenerare tutto
Richiede **FreeCAD 1.1** (usa `FreeCADCmd`, headless) e l'addon **SheetMetal**
(+ `networkx`) per l'unfold.

```powershell
cd hardware/freecad
& "C:\Program Files\FreeCAD 1.1\bin\FreeCADCmd.exe" streamer_sheetmetal.py   # STEP + STL
& "C:\Program Files\FreeCAD 1.1\bin\FreeCADCmd.exe" unfold.py                # DXF sviluppati
& "C:\Program Files\FreeCAD 1.1\bin\FreeCADCmd.exe" verify.py                # verifica
```

Tutte le quote sono **parametriche** in cima a `streamer_sheetmetal.py`: cambia un
numero (es. una misura di un componente) e rigenera.

---

## 4. Ordinare su JLCPCB

1. Servizio **Sheet Metal Fabrication**
2. Carica i **5 file STEP singoli** da `out/` (non l'assembly)
3. Per ogni pezzo:
   - Material: **Aluminum** → **Aluminum 5052**
   - Surface Finish: **No** (grezzo) *oppure* **Yes** se vuoi anodizzato/verniciato
   - Configure Sub-assembly: **No** · Welding: **No** · Threads and Tapped Holes: **No**
   - Product Desc: *Aluminum Alloy Enclosure (HS 761699)*
   - Qty: **1**
4. I pezzi grandi (`body`, `front`, `lid`) vanno in **manual quote** (prezzo da operatore
   in 2-4 h): è normale, dovuto alla dimensione dello sviluppo piatto, non è un errore.

> JLC **sviluppa la lamiera dallo STEP** (taglio + piega): non serve caricare i DXF.
> Lo spessore (2 mm) viene letto dal file. I raggi di piega li applica JLC in automatico.

### Laser marking (scritta) — opzionale
Più economico del silkscreen. Carica `out/silkscreen-front.dxf` sull'opzione
**Laser Marking** del pezzo `front`. Resa migliore su finitura **scura** (su alluminio
grezzo il segno è poco contrastato).

---

## 5. Hardware da acquistare

- **Viti M3×8 autofilettanti per lamiera** (oppure viti normali + **inserti/rivetti filettati
  M3** — su 2 mm il filetto diretto non tiene, meglio inserti PEM o viti autofilettanti)
  — **20 pz** (16 squadrette front/back + 4 ripiano: spessore lamiera 2mm
  + presa nella squadretta/aletta, 8mm basta e non sfonda l'altra faccia)
- **Viti M3×10 a macchina**, testa cilindrica/bombata — **4 pz** (schermo: attraversano
  rondella larga + foro maggiorato Ø5.5 e si serrano con **dado dietro la scheda**;
  nel pannello NON fanno presa, il foro è maggiorato apposta)
- **Squadrette a L interne** (staffa piccola **15×15×1.5 mm**, es. alluminio o acciaio
  zincato; meglio con **fori ad asola**) — **8 pz**: 6 per il retro (3 livelli per lato)
  + 2 per il frontale (**solo livello basso**: a metà e in alto c'è il modulo schermo,
  z ≈ 38–162 mm, e non c'è spazio per squadrette o teste di vite — quei fori restano vuoti)
- **Barre filettate M3, Ø3mm, tagliate a ~168 mm** (tiranti fondo↔coperchio) — **6 pz**
  (servono **2 barre da 1 m**: 6×168 mm più il taglio non ci sta in una sola) — tengono
  insieme fondo e coperchio (il coperchio **non** si avvita ai fianchi, non ci sono risvolti)
- **Dadi M3** — **16 pz** (2 per tirante + 4 dietro la scheda schermo) + **Rondelle M3** —
  **16 pz** (2 per tirante + 4 schermo; quelle schermo **larghe**, Ø esterno 9–12 mm,
  per coprire il gioco del foro Ø5.5)
- **Jack DC**: barrel panel-mount **"DC-022"** (foro 8 mm), barrel adatto al PC (es. 5.5×2.5)
- **Doppia USB-A** panel-mount, viti a **interasse 28 mm**
- **RJ45** panel-mount, viti a **interasse 27.1 mm**
- **Biadesivo** forte (per CD e mini PC)

---

## 6. Istruzioni di montaggio

> Tutte le viti sono **M3**. I fori da Ø2.6 sono prefori (autofilettante/inserto),
> quelli da Ø3.4 sono passanti. I fori schermo sono Ø5.5 (con rondella, per tolleranza).

### Passo 1 — Schermo sul frontale
1. Appoggia lo schermo **dietro** al pannello `front`, area visibile centrata nella finestra.
2. Allinea i 4 fori della scheda ai 4 fori Ø5.5 del frontale.
3. Avvita con **4 viti M3×10 a macchina + rondelle larghe**, serrate con **dado M3
   dietro la scheda** (le rondelle coprono il gioco dei fori maggiorati).
   - Se l'allineamento è leggermente fuori, i fori Ø5.5 danno ±1 mm di gioco.

### Passo 2 — Connettori sul retro
1. Monta sul pannello `back`:
   - **doppia USB-A** (2 viti M3, interasse 28 mm)
   - **jack DC** DC-022 nel foro da 8 mm (stringi col dado)
   - **RJ45** (2 viti M3, interasse 27.1 mm)

### Passo 3 — Lettore CD nel corpo
1. Incolla il **lettore CD** sul **fondo** del corpo con biadesivo,
   con il frontalino/cassetto allineato alla **fessura** del pannello `front`.

### Passo 4 — Ripiano + mini PC
1. Avvita il **ripiano** (`shelf`) ai due **fianchi** del corpo:
   le alette del ripiano si avvitano dall'esterno dei fianchi (viti M3, 2 per lato).
2. Incolla il **mini PC** sul ripiano con biadesivo, verso la parte anteriore,
   lasciando lo spazio posteriore libero per i cavi.

### Passo 5 — Cablaggio (prima di chiudere)
1. Collega lo **schermo** al mini PC (HDMI + USB touch/alimentazione).
2. Collega il **lettore CD** a una USB del PC.
3. Porta i cavi dei **connettori posteriori** alle rispettive porte del PC
   (rete, USB esterne, alimentazione DC). Usa lo spazio dietro al PC (~70 mm).

### Passo 6 — Frontale e retro sui fianchi
> Frontale e retro sono pannelli **piatti** (nessun risvolto): si fissano ai fianchi del
> corpo con **squadrette a L interne** ai livelli `bz` = basso / metà / alto. Ogni
> squadretta prende **2 viti**: una in orizzontale-profondità (dal pannello nella
> squadretta) e una in orizzontale-larghezza (dal fianco nella squadretta).
>
> ⚠ **Frontale: solo il livello basso.** I fori a metà e in alto (z ≈ 86 / 142 mm)
> cadono dietro il modulo schermo (z ≈ 38–162 mm): non c'è spazio per squadrette né
> teste di vite. Restano inutilizzati. Il frontale è comunque tenuto anche dai
> 3 tiranti anteriori (a 9 mm dal pannello) e irrigidito dallo schermo avvitato.
1. **Frontale** (`front`): 1 squadretta per fianco al **livello basso**; avvita
   **2 viti** dal pannello + **2 viti** dai fianchi = **4 viti**.
2. **Retro** (`back`): 3 squadrette per fianco (3 livelli); avvita **6 viti** dal
   pannello + **6 viti** dai fianchi = **12 viti**.

### Passo 7 — Tiranti fondo↔coperchio e chiusura
> Il coperchio **non si avvita ai fianchi** (non ci sono risvolti): fondo e coperchio sono
> tenuti insieme da **6 tiranti filettati M3** (~168 mm) che attraversano l'interno,
> allineati verticalmente (stesse X/Y sia nel fondo che nel coperchio).
1. Avvita un **dado + rondella** su ogni tirante, infilalo dal **fondo** (dall'esterno,
   sotto il corpo) nei 6 fori corrispondenti, e blocca con un secondo dado dall'interno
   (o lascialo sporgere se preferisci bloccare tutto solo alla fine).
2. Appoggia il **coperchio** sopra, infilando i 6 tiranti nei fori corrispondenti
   (stessa griglia X/Y del fondo).
3. Blocca ogni tirante dall'alto con **rondella + dado**, serrando fondo e coperchio
   l'uno verso l'altro.

A questo punto la scocca è chiusa. Consiglio: non serrare a fondo i dadi finché non hai
richiuso tutti e 6 i tiranti, per poter correggere l'allineamento.

---

## 7. Tolleranze e note

- Spessore lamiera 2 mm; raggio di piega applicato da JLC (~2 mm interno).
- I fori schermo (ora Ø6.5) sono volutamente maggiorati: c'è gioco per recuperare
  piccoli errori di interasse. In alluminio grezzo è comunque facile riforare/limare.
  - **Lotto 1 (prodotto con interasse 152.1 × 113.1 e fori Ø5.5)**: l'interasse reale
    dello schermo è **156 × 115** → allargare a lima i 4 fori di ~2 mm verso l'esterno
    in orizzontale (e ~1 mm in verticale); le rondelle larghe coprono l'occhiello.
- Centratura finestra schermo: `view_offy = 0` (area attiva centrata sui fori).
  Regolabile ±5 mm in `streamer_sheetmetal.py` se vedi un bordo nero asimmetrico.
- Diametri/interassi connettori sono quelli dei componenti acquistati: se cambi
  connettore, aggiorna i parametri in `streamer_sheetmetal.py` e rigenera.
