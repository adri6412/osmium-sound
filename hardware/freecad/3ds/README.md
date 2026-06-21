# Scocca Network Streamer HiFi — versione STAMPA 3D

Riadattamento per **stampa 3D FDM** del progetto in lamiera
([`../../README.md`](../../README.md)). La lamiera prende rigidità dalle
**pieghe**, che in plastica non esistono: qui la scocca è una **scatola a 6
pannelli piatti imbullonati** + ripiano interno.

Le **misure funzionali sono identiche** alla versione in alluminio
(finestra schermo, 4 fori schermo a interasse 152.1 × 113.1, fessura CD,
fori connettori, quota ripiano). Cambiano **solo spessori e giunzioni**.

---

## Cosa cambia rispetto alla lamiera

| | Lamiera | Stampa 3D |
|---|---|---|
| Pareti | 2 mm piegati | **3 mm** pieni |
| Rigidità | dalle pieghe | da **montanti d'angolo** integrati nei fianchi |
| Fissaggio | autofilettanti / inserti su 2 mm | **inserti M3 a caldo** (heat-set) nei montanti |
| Pezzi | 5 (corpo a U + 4) | **7** pannelli piatti |
| Esterno | 180.9 × 172.3 × 220 | **182.9 × 174.3 × 222** (+1 mm/lato per le pareti) |

---

## I 7 pezzi (`out/`)

| Pezzo | File | Note stampa |
|---|---|---|
| Fondo | `streamer3d-body-bottom` | piatto, faccia in giù |
| Coperchio | `streamer3d-lid` | piatto, feritoie ventilazione |
| Fianco sx | `streamer3d-side-left` | montanti + appoggi ripiano integrati |
| Fianco dx | `streamer3d-side-right` | speculare |
| Frontale | `streamer3d-front` | finestra schermo + fessura CD |
| Retro | `streamer3d-back` | fori USB / DC / RJ45 |
| Ripiano | `streamer3d-shelf` | porta mini PC |

`streamer3d-assembly.step` è solo l'anteprima d'assieme: **non stamparlo**.

Ogni pannello è piatto → si stampa appoggiato sul piano. Ingombri max
(per controllare il piano della stampante):
- fianchi: **222 × 168 mm** → servono ~**220 mm** di lato
- fondo / coperchio: **183 × 222 mm**
- frontale / retro: **177 × 168 mm**

> Con un piano **220 × 220** (Ender 3 ecc.) i fianchi e fondo/coperchio
> entrano al pelo, meglio orientarli in diagonale. Con **256 × 256**
> (Bambu / Prusa XL) nessun problema.

---

## Stampa consigliata

- **Materiale: PETG** (o ABS/ASA). **NO PLA**: dentro hai mini PC + CD che
  scaldano e il PLA si ammorbidisce a ~60 °C.
- Parete: **3–4 perimetri**, **infill 25–30 %** (i pannelli sono strutturali).
- Layer 0.2 mm. Brim consigliato sui pannelli grandi per l'adesione.
- Le feritoie del coperchio (`lid`) e del ripiano vanno **tenute**: servono
  per smaltire il calore.

### Inserti filettati
I fori da Ø4.0 mm nei montanti e negli appoggi del ripiano sono per
**inserti M3 a caldo (heat-set, knurled)**. Si inseriscono col saldatore
**prima** del montaggio, dalla faccia accessibile.
- PLA/PETG: foro Ø4.0 va bene. ABS: meglio Ø4.2.
- Se usi inserti diversi, cambia `ins_d` in cima a `streamer_3dprint.py` e
  rigenera.

---

## Ferramenta

- **Inserti M3 a caldo**: 4 (fondo) + 4 (coperchio) + 8 (front/back) + 4
  (ripiano) = **20 inserti M3**
- **Viti M3**: testa cilindrica/svasata
  - fondo→montanti: 4 (lunghezza ≈ `3 + 8` mm → M3×10/12)
  - coperchio→montanti: 4 (M3×10/12)
  - front→montanti: 4 · back→montanti: 4 (M3×10)
  - ripiano→appoggi: 4 (M3×8/10)
- **4 viti M3 + rondelle** per lo schermo (fori Ø5.5 maggiorati)
- Connettori posteriori e biadesivo: **identici** alla versione lamiera
  (vedi [`../../README.md`](../../README.md) §5).

---

## Montaggio

1. **Inserti**: pressa i 20 inserti M3 a caldo in tutti i fori Ø4.0
   (montanti dei due fianchi: 4 verticali + 2 orizzontali ciascuno;
   appoggi ripiano: 2 per fianco).
2. **Schermo** sul `front` (4 viti M3 + rondelle), **connettori** sul `back`
   — come la versione lamiera.
3. Metti in piedi i due **fianchi**; avvita **frontale** e **retro** ai
   montanti (8 viti orizzontali). Ora hai un tubo rigido.
4. Avvita il **fondo** dal basso nei 4 montanti (4 viti).
5. Incolla il **lettore CD** sul fondo (biadesivo), allineato alla fessura.
6. Avvita il **ripiano** agli appoggi dei fianchi (4 viti dall'alto);
   incolla il **mini PC** sul ripiano (biadesivo), verso il davanti.
7. **Cablaggio** (schermo↔PC, CD↔USB, connettori posteriori). Usa il
   passacavi del ripiano e lo spazio dietro al PC.
8. Appoggia il **coperchio** e avvitalo dall'alto nei 4 montanti.

---

## Rigenerare

Richiede **FreeCAD 1.1** (`FreeCADCmd`, headless). Non serve l'addon
SheetMetal: qui è geometria solida pura.

```powershell
cd hardware/freecad/3ds
& "C:\Program Files\FreeCAD 1.1\bin\FreeCADCmd.exe" streamer_3dprint.py
```

Tutte le quote sono parametriche in cima a `streamer_3dprint.py`
(spessore `wt`, montanti `post`, foro inserto `ins_d`, viti `clr_d`).
Lo script stampa a video le **dimensioni esterne**, il **check dei solidi**
(volume + validità) e il **check interferenze** tra i pezzi.
