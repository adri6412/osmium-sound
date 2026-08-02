// =====================================================================
//  Squadretta a L stampabile - fissaggio Frontale/Retro <-> Fianchi
//  HIFI STREAMER case
//  ---------------------------------------------------------------
//  Sostituisce la "staffa 15x15x1.5mm" comprata (vedi hardware/README.md
//  § 5 "Hardware da acquistare"), che nel case reale non entra/non
//  allinea bene con i fori.
//
//  Misure derivate DIRETTAMENTE dai parametri usati per tagliare la
//  lamiera reale (hardware/freecad/streamer_sheetmetal.py):
//    - spessore lamiera nominale    = 2.0 mm (t nello script lamiera)
//    - offset foro lato fianco     = fl/2               = 9.0 mm  (y_front / y_back)
//    - offset foro lato pannello   = bracket_edge - t   = 6.5 mm  (bracket_edge=10,
//      corretto di -t perché lo spigolo interno della L appoggia sulla faccia
//      INTERNA del fianco, a X=t dal bordo esterno del case, non su X=0.
//      Qui t=3.5mm: NON è più lo spessore nominale lamiera (2.0mm) ma un
//      valore ricalibrato misurando il case reale, per avvicinare il foro
//      pannello allo spigolo e togliere la staffa dall'ingombro che sporgeva.)
//    - viti usate: M3x8 autofilettanti (elemento "①b" nella distinta)
//    - livelli Z staffe: 30 / 86.1 / 142.3 mm dal fondo (bz nel CAD)
//      -> sul FRONTALE si usa SOLO il livello basso (30mm): al centro/alto
//         c'e' lo schermo e non c'e' spazio. Sul RETRO tutti e 3 i livelli.
//      -> la staffa e' identica per tutte le posizioni: stessa parte,
//         serve in 8 esemplari (2 frontale + 6 retro).
//
//  NOTA IMPORTANTE sui fori: nel CAD della lamiera il foro nel fianco è
//  "clearance" (Ø3.4) e quello nel pannello frontale/retro è "pilota"
//  (Ø2.6, pensato per autofilettarsi nell'alluminio da 2mm). Per una
//  staffa STAMPATA è più affidabile far avvitare la vite autofilettante
//  SEMPRE nella staffa in plastica (più materiale, presa migliore) e
//  trattare i fori nella lamiera come semplice passaggio. Per questo qui
//  entrambi i fori della staffa sono "pilota" di default: se nel tuo case
//  un foro lamiera risulta troppo stretto, allargalo a Ø3.2-3.4mm con un
//  trapano a mano (la vite deve scorrere libera nella lamiera e mordere
//  solo nella staffa).
//
//  Se le misure non combaciano col tuo case fisico (il progetto è
//  segnalato come BETA/non validato in hardware/README.md), misura con
//  un calibro la posizione reale dei fori e correggi i parametri sotto.
// =====================================================================

// --------------------- PARAMETRI (modifica qui) ---------------------

// Lunghezza delle due gambe della staffa, misurata dallo spigolo interno
leg_fianco    = 33.2;   // gamba che appoggia sul FIANCO del corpo
leg_pannello  = 15;   // gamba che appoggia sul pannello FRONTALE/RETRO

// "Profondità" della staffa (asse lungo cui è estrusa la L) [mm]
larghezza     = 15;

// Spessore pareti stampate [mm]
// (l'originale comprato è lamiera da 1.5mm: troppo sottile per una vite
//  autofilettante in plastica -> qui più spesso per tenuta del filetto)
spessore      = 3;

// Spessore lamiera del case (t nel CAD lamiera) [mm]
// Serve per correggere l'offset del foro "pannello": lo spigolo interno
// della L appoggia sulla faccia INTERNA del fianco, che sta a X=t dal
// bordo esterno del case, mentre bracket_edge è misurato dal bordo
// esterno (X=0). Senza questa correzione il foro pannello risulta
// spostato di t mm rispetto ai fori reali di front/back (il foro fianco
// invece non ne ha bisogno: il suo asse combacia già col datum del body).
t = 3;

// Offset dei fori dallo spigolo interno della L, lungo la rispettiva gamba
// (presi identici al CAD della lamiera: fl/2 e bracket_edge)
foro_fianco_offset    = 12;        // = fl/2 = 18/2
foro_pannello_offset  = 10 - t;   // = bracket_edge - t (vedi nota sopra)

// Diametri fori per vite M3 autofilettante (pilota: si avvita nella staffa)
d_foro_fianco    = 2.6;
d_foro_pannello  = 2.6;

// Se true, stampa una piastra con 8 copie (6 retro + 2 frontale) pronte
// per un'unica stampa; se false, stampa un solo pezzo.
stampa_piastra_8pz = false;

$fn = 48;

// --------------------------- MODULO ----------------------------------

module squadretta() {
    difference() {
        union() {
            // gamba contro il FIANCO (piano Y-Z, spessore lungo X)
            cube([spessore, leg_fianco, larghezza]);
            // gamba contro il PANNELLO frontale/retro (piano X-Z, spessore lungo Y)
            cube([leg_pannello, spessore, larghezza]);
        }
        // foro sulla gamba "fianco" - asse del foro lungo X
        translate([-1, foro_fianco_offset, larghezza / 2])
            rotate([0, 90, 0])
                cylinder(d = d_foro_fianco, h = spessore + 2);

        // foro sulla gamba "pannello" - asse del foro lungo Y
        translate([foro_pannello_offset, -1, larghezza / 2])
            rotate([-90, 0, 0])
                cylinder(d = d_foro_pannello, h = spessore + 2);
    }
}

// --------------------------- OUTPUT -----------------------------------

if (stampa_piastra_8pz) {
    passo = max(leg_fianco, leg_pannello) + 5;
    for (i = [0:7]) {
        translate([floor(i / 4) * passo, (i % 4) * passo, 0])
            squadretta();
    }
} else {
    squadretta();
}
