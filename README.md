# Osmium Sound

**Osmium Sound** is an audiophile network music player built on
[Lyrion Music Server](https://lyrion.org/) (LMS), shipped as a ready-to-flash
OS image for x86 mini-PCs and Raspberry Pi, with a bit-perfect audio path, a
10-foot Qt UI for the TV, a web admin, and over-the-air (OTA) updates.

Website: **[osmiumsound.it](https://osmiumsound.it)** ·
Downloads: **[osmiumsound.it/#download](https://osmiumsound.it/#download)**

This repository is the project landing page. The code lives in the
sub-repositories below.

---

## Repositories

| Repo | What it is |
| --- | --- |
| [**osmium-sound-x86**](https://github.com/adri6412/osmium-sound-x86) | x86 OS image & player (the installable ISO / `.img.xz`). Formerly `osmium-sound`. |
| [**osmium-sound-raspberry**](https://github.com/adri6412/osmium-sound-raspberry) | Raspberry Pi OS image & player (CM5 / Pi 5 / Pi 4). |
| [**osmium-core**](https://github.com/adri6412/osmium-core) | Shared application code (API, Qt UI, web admin, recommender). Used as the `core/` submodule by both image repos. |
| [**osmium-sound-site**](https://github.com/adri6412/osmium-sound-site) | The osmiumsound.it website and the OTA publishing pipeline (Cloudflare Pages). |
| [**osmium-companion-android**](https://github.com/adri6412/osmium-companion-android) | Android companion app (available on F-Droid). |

The two image repos (`osmium-sound-x86`, `osmium-sound-raspberry`) share their
application layer through the `osmium-core` submodule; only the
platform layer (boot, OTA, CI, DAC/CamillaDSP wiring) differs between them.

---

## Osmium Sound (italiano)

**Osmium Sound** è un lettore musicale di rete audiophile basato su
[Lyrion Music Server](https://lyrion.org/) (LMS), distribuito come immagine di
sistema pronta da scrivere su mini-PC x86 e Raspberry Pi, con percorso audio
bit-perfect, interfaccia Qt "10-foot" per il televisore, pannello web di
amministrazione e aggiornamenti over-the-air (OTA).

Sito: **[osmiumsound.it](https://osmiumsound.it)** ·
Download: **[osmiumsound.it/#download](https://osmiumsound.it/#download)**

Questo repository è la pagina di presentazione del progetto. Il codice si trova
nei sotto-repository:

| Repo | Cos'è |
| --- | --- |
| [**osmium-sound-x86**](https://github.com/adri6412/osmium-sound-x86) | Immagine e player x86 (la ISO / `.img.xz` installabile). Prima si chiamava `osmium-sound`. |
| [**osmium-sound-raspberry**](https://github.com/adri6412/osmium-sound-raspberry) | Immagine e player per Raspberry Pi (CM5 / Pi 5 / Pi 4). |
| [**osmium-core**](https://github.com/adri6412/osmium-core) | Codice applicativo condiviso (API, UI Qt, admin web, consigliati). Usato come submodule `core/` dai due repo immagine. |
| [**osmium-sound-site**](https://github.com/adri6412/osmium-sound-site) | Il sito osmiumsound.it e la pipeline di pubblicazione OTA (Cloudflare Pages). |
| [**osmium-companion-android**](https://github.com/adri6412/osmium-companion-android) | App companion per Android (disponibile su F-Droid). |

I due repo immagine (`osmium-sound-x86`, `osmium-sound-raspberry`) condividono il
livello applicativo tramite il submodule `osmium-core`; tra loro cambia solo il
livello di piattaforma (boot, OTA, CI, DAC/CamillaDSP).
