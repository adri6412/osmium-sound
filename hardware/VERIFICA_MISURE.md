# Verifica Misure - Streamer Wood Laser Cut

## Dimensioni Esterne Calcolate
- **Larghezza (W)**: max(164.9, 137.2, 120.0) + 2×6 + 2×5 = 164.9 + 22 = **186.9 mm** ✓
- **Altezza (H)**: (5 + 2) + 141.2/2 + 16 + 124.27/2 + 8 + 5 = **178.27 mm** ✓
- **Profondità (Dch)**: 220 - 2×5 = **210 mm** ✓

## Componenti Interni vs Spazi

### Schermo Waveshare 7" (C)
- **Dimensioni**: 164.9 W × 124.27 H mm
- **Area visiva**: 154.21 W × 85.92 H mm
- **Fori montaggio**: interasse 152.1 × 113.1 mm
- **Spazio disponibile frontale**: 186.9 - 2×6 = 174.9 mm (OK, 174.9 > 164.9) ✓
- **Posizione Y schermo**: z0 = 7 + 18 = 25, centro a 25 + 62 = 87.1 mm
- **Finestra DXF**: view_w=154.21, view_h=85.92, centro a 89.15 mm (OK) ✓

### Lettore CD Slim
- **Dimensioni**: 137.2 W × 137.2 D × 15 H mm
- **Spazio larghezza**: 186.9 - 2×6 = 174.9 mm (OK, 174.9 > 137.2) ✓
- **Posizione Z**: slot_z0 = 5 + 2 = 7 mm, centro slot a 7 + 9 = 16 mm
- **Slot DXF**: z_cd_c = 16 mm ✓
- **Spazio profondità**: 210 mm (OK, 210 > 137.2) ✓

### Mini PC BMAX N100
- **Dimensioni**: 120 W × 120 D × 32 H mm
- **Spazio larghezza**: 186.9 - 2×6 = 174.9 mm (OK, 174.9 > 120) ✓
- **Posizione Z**: shelf_z = 5 + 0 + 15 + 4 = 24 mm (OK, sopra CD) ✓
- **Spazio profondità**: 210 mm (OK, 210 > 120) ✓

### Ripiano (Shelf)
- **Lunghezza**: pc_d + 20 = 120 + 20 = 140 mm
- **Posizione Y**: shelf_y0 = 21 mm, da 21 a 161 mm
- **Spazio disponibile**: 210 - 2×10 = 190 mm (OK) ✓
- **Fori montaggio**: Y = [46, 136] mm
  - Centro del pannello: 210/2 = 105 mm
  - PROBLEMA: Fori a 46 e 136, non simmetrici intorno a 105 ✗

## Accessi Frontali

### Finestra Schermo
- **Dimensioni apertura**: 154.21 × 85.92 mm
- **Posizione**: centro a X=93.45, Z=89.15
- **Fori montaggio schermo**: (93.45±76.05, 89.15±56.55) = punti agli angoli ✓

### Fessura CD
- **Dimensioni**: 141.2 × 18 mm
- **Posizione**: centro a X=93.45, Z=16 mm ✓
- **Spazio**: libero tra CD e schermo (16+9 vs 87-43 = 25 > 44) - OK ✓

## Accessi Posteriori

### USB Doppia
- **Apertura**: 14 × 16 mm
- **Posizione**: X = 186.9 × 0.28 = 52.3 mm ✓

### DC Jack
- **Apertura**: ⌀8 mm
- **Posizione**: X = 186.9 × 0.55 = 102.8 mm (centro) ✓

### RJ45
- **Apertura**: 17 × 15 mm
- **Posizione**: X = 186.9 × 0.78 = 145.8 mm ✓

## Fori Viti

### Front
- **Montaggio schermo**: 4 fori agli angoli ✓
- **Fissaggio fianchi**: 4 fori (SX/DX × 2 altezze) ✓

### Back
- **Connettori**: 4 fori viti (USB 2 + RJ45 2) ✓
- **Fissaggio fianchi**: 4 fori (SX/DX × 2 altezze) ✓

### Side
- **Coperchio**: 3 fori a Y=[25, 105, 185], Z=163 mm ✓
- **Ripiano**: 2 fori a Y=[46, 136], Z=16 mm ⚠️ **NON AL CENTRO**

## Problemi Identificati

1. **Fori ripiano non al centro**: Y=[46, 136] dovrebbero essere a Y=[30, 180] o Y=[50, 160] per essere simmetrici
2. **Fori ripiano posizionamento Z**: A Z=16mm sono corretti (shelf_z - 8) ✓

## Azioni Necessarie

- [ ] Spostare fori ripiano al centro: Y = [Dch/2 - 35, Dch/2 + 35] = [70, 140] mm
- [ ] Verificare altezza coperchio e spazio finale
- [ ] Verificare incastri tra pezzi (attualmente solo incollati)

