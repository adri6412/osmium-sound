# Allineamento Fori - Verifica Montaggio

## Schema di Montaggio

```
          COPERCHIO (Lid)
              ↕ viti
      SIDE_LEFT --- SIDE_RIGHT
         ↕ ↕          ↕ ↕
    FRONT BACK    FRONT BACK
         ↕ ↕          ↕ ↕
        BOTTOM
           ↕ viti
        SHELF
```

## Fori per Componente

### BOTTOM (Fondo)
- **Tipo**: nessun foro (incollato ai side)
- **Fissaggio**: incastri (no viti)

### SIDE_LEFT / SIDE_RIGHT (Fianchi)
- **Coperchio**: 3 fori a Y=[25, 105, 185], Z=163mm ✓
- **Ripiano**: 2 fori a Y=[70, 140], Z=89mm ✓
- **Front/Back**: 0 fori (incollati, no viti) ⚠️ **CONTROLLO NECESSARIO**

### FRONT (Frontale)
- **Schermo**: 4 fori di montaggio (angoli) ✓
- **Fissaggio fianchi**: 4 fori a Y=5, Z=[30, H-30] ⚠️ **MA I FIANCHI NON HANNO QUESTI FORI!**

### BACK (Posteriore)
- **Connettori**: 4 fori viti (USB 2 + RJ45 2) ✓
- **Fissaggio fianchi**: 4 fori a Y=5, Z=[30, H-30] ⚠️ **MA I FIANCHI NON HANNO QUESTI FORI!**

### LID (Coperchio)
- **Fissaggio fianchi**: 6 fori a X=[t+5, W-t-5], Y=[25, 105, 185] ✓
- **Ventilazione**: 3 asole rettangolari ✓

### SHELF (Ripiano)
- **Montaggio fianchi**: fori allineati con side ✓

## Problemi Identificati

1. **Front/Back hanno fori di fissaggio ai fianchi (Y=5, Z=[30, 150-30])**
   - Ma i **SIDE NON HANNO** questi fori!
   - Soluzione: O rimuovere fori da front/back, oppure aggiungerli ai side

2. **Decisione**: Poiché abbiamo detto che front/back sono **INCOLLATI**, non dovrebbero avere viti!
   - **AZIONE**: Rimuovere i 4 fori dai side per il fissaggio front/back

## Verifica Finale Richiesta

- [ ] Controllare coerenza fori side ↔ front ↔ back
- [ ] Controllare coerenza fori side ↔ lid
- [ ] Controllare coerenza fori side ↔ shelf
- [ ] Verificare che ogni foro nel side abbia un corrispettivo nel pezzo che si attacca

## File VERIFICA_MISURE.md

Usa questo file per:
1. Verificare che dimensioni componenti interni < spazi disponibili
2. Controllare che non ci siano collisioni
3. Assicurarsi che tutto entri dentro la scatola

