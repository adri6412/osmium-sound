"""Per-request i18n for the appliance's Python backends (api_server.py,
sources_server.py, webui_server.py).

Both frontends (the Electron kiosk and the Vue admin-webui) have their own
working i18n system and let the owner pick English or Italian — but every
backend JSON response used to carry a `message` string hardcoded in Italian.
An English-locale user would still see raw Italian text for every error/status
toast in Settings, because both frontends render `response.message` verbatim
when present, only falling back to their own translated string when it's
missing. This module is the fix: a flat `MESSAGES` catalog keyed by a stable
dotted `code` (the same `namespace.name` convention a handful of endpoints
already used, e.g. `ssh.installFailed`), and a `t()` that looks a code up in
the caller's language.

This mirrors sources_server.py's own SOURCES_I18N/`_t()` (used for its
self-contained Sources web page), but is meant to be shared by everything
that returns `{'success': False, 'message': ...}`-shaped JSON, so it lives in
its own dependency-free module rather than being duplicated per-file.
"""

MESSAGES = {
    # ── Network (Wi-Fi / wired) ─────────────────────────────────────
    'network.ssidMissing': {'en': 'Missing SSID', 'it': 'SSID mancante'},
    'network.invalidField': {'en': '{label} is invalid', 'it': '{label} non valido'},
    'network.connectTimeout': {'en': 'Connection timed out', 'it': 'Timeout durante la connessione'},
    'network.connectFailed': {'en': 'Connection failed', 'it': 'Connessione fallita'},
    'network.connected': {'en': 'Connected to {ssid}', 'it': 'Connesso a {ssid}'},
    'network.noEthernet': {'en': 'No Ethernet interface found', 'it': 'Nessuna interfaccia Ethernet trovata'},
    'network.wiredFailed': {'en': 'Wired connection failed', 'it': 'Connessione via cavo fallita'},
    'network.wiredConnected': {'en': 'Connected via cable', 'it': 'Connesso via cavo'},
    'network.cableNotConnected': {'en': 'Cable not connected', 'it': 'Cavo non connesso'},

    # ── Audio output (DAC) ──────────────────────────────────────────
    'audio.deviceMissing': {'en': 'Missing device', 'it': 'Device mancante'},
    'audio.invalidDevice': {'en': 'Invalid audio device: {device}', 'it': 'Dispositivo audio non valido: {device}'},
    'audio.dspOutputFailed': {'en': 'Setting output (DSP) failed', 'it': 'Impostazione uscita (DSP) fallita'},
    'audio.dspOutputSet': {'en': 'Audio output (DSP) set to {device}', 'it': 'Uscita audio (DSP) impostata su {device}'},
    'audio.writeConfigFailed': {'en': 'Writing the configuration failed', 'it': 'Scrittura configurazione fallita'},
    'audio.deviceSetRestartWarn': {'en': 'Device set ({device}); squeezelite restart: {err}',
                                   'it': 'Device impostato ({device}); riavvio squeezelite: {err}'},
    'audio.deviceSetRestartFailed': {'en': 'Device set ({device}); restart failed',
                                     'it': 'Device impostato ({device}); riavvio non riuscito'},
    'audio.outputSet': {'en': 'Audio output set to {device}', 'it': 'Uscita audio impostata su {device}'},
    'audio.defaultDeviceName': {'en': 'System default', 'it': 'Predefinito di sistema'},

    # ── Multiroom / Lyrion server role ──────────────────────────────
    'lms.invalidIp': {'en': 'Invalid IP address: {host}', 'it': 'Indirizzo IP non valido: {host}'},
    'lms.useLocalMode': {'en': 'Use "This device" mode for the local server',
                         'it': 'Usa la modalità "Questo dispositivo" per il server locale'},
    'lms.invalidMode': {'en': 'Invalid mode: {mode}', 'it': 'Modalità non valida: {mode}'},
    'lms.sqConfigMissing': {'en': 'squeezelite configuration not found', 'it': 'Configurazione squeezelite non trovata'},
    'lms.serverSetRestartWarn': {'en': 'Server set ({target}); squeezelite restart: {err}',
                                 'it': 'Server impostato ({target}); riavvio squeezelite: {err}'},
    'lms.serverSetRestartFailed': {'en': 'Server set ({target}); restart failed',
                                   'it': 'Server impostato ({target}); riavvio non riuscito'},
    'lms.localRestored': {'en': 'Local Lyrion server restored', 'it': 'Ripristinato il server Lyrion locale'},
    'lms.serverSet': {'en': 'Lyrion server set to {target}', 'it': 'Server Lyrion impostato su {target}'},

    # ── Player name ──────────────────────────────────────────────────
    'player.invalidName': {'en': 'Invalid name: letters, numbers, dot, dash and underscore only, '
                                  'no spaces (max 24 characters)',
                           'it': 'Nome non valido: solo lettere, numeri, punto, trattino e underscore, '
                                 'senza spazi (max 24 caratteri)'},
    'player.nameSetRestartWarn': {'en': 'Name set ({name}); squeezelite restart: {err}',
                                  'it': 'Nome impostato ({name}); riavvio squeezelite: {err}'},
    'player.nameSetRestartFailed': {'en': 'Name set ({name}); restart failed',
                                    'it': 'Nome impostato ({name}); riavvio non riuscito'},
    'player.nameSet': {'en': 'Player name set to {name}', 'it': 'Nome player impostato su {name}'},
    'player.toggleFailed': {'en': 'The player on/off operation failed.',
                            'it': "L'operazione di accensione/spegnimento del player non è riuscita."},
    'player.enabled': {'en': 'Player enabled.', 'it': 'Player abilitato.'},
    'player.disabled': {'en': 'Player disabled.', 'it': 'Player disabilitato.'},

    # ── SSH ──────────────────────────────────────────────────────────
    'ssh.installFailed': {'en': 'Could not install openssh-server.',
                          'it': 'Impossibile installare openssh-server.'},
    'ssh.toggleFailed': {'en': 'The SSH operation failed.', 'it': "L'operazione SSH non è riuscita."},
    'ssh.enabled': {'en': 'SSH enabled.', 'it': 'SSH abilitato.'},
    'ssh.disabled': {'en': 'SSH disabled.', 'it': 'SSH disabilitato.'},

    # ── Shell (SSH/console) account ────────────────────────────────
    'shell.badUsername': {'en': 'Invalid username: use 3-32 lowercase letters, digits, - or _.',
                          'it': 'Nome utente non valido: usa 3-32 lettere minuscole, cifre, - oppure _.'},
    'shell.reservedUsername': {'en': 'The name "{username}" is reserved by the system.',
                               'it': 'Il nome "{username}" è riservato dal sistema.'},
    'shell.shortPassword': {'en': 'The password must be at least 8 characters long.',
                            'it': 'La password deve contenere almeno 8 caratteri.'},
    'shell.badPassword': {'en': 'The password cannot contain ":" or a line break.',
                          'it': 'La password non può contenere ":" o un a capo.'},
    'shell.createFailed': {'en': 'Could not create the login. See the system log for details.',
                           'it': "Impossibile creare l'utenza. Controlla il log di sistema per i dettagli."},

    # ── Tailscale ────────────────────────────────────────────────────
    'tailscale.alreadyInstalled': {'en': 'Tailscale is already installed', 'it': 'Tailscale è già installato'},
    'tailscale.installFailedNetwork': {'en': 'Tailscale installation failed — check your Internet '
                                              'connection and try again',
                                       'it': 'Installazione di Tailscale fallita — controlla la connessione '
                                             'a Internet e riprova'},
    'tailscale.installFailed': {'en': 'Tailscale installation failed', 'it': 'Installazione di Tailscale fallita'},
    'tailscale.installed': {'en': 'Tailscale installed', 'it': 'Tailscale installato'},
    'tailscale.notInstalled': {'en': 'Tailscale is not installed on this device. Complete the system '
                                      'update and try again.',
                               'it': "Tailscale non è installato sul dispositivo. Completa l'aggiornamento "
                                     'di sistema e riprova.'},
    'tailscale.enableFailed': {'en': 'Enabling Tailscale failed', 'it': 'Attivazione Tailscale fallita'},
    'tailscale.disableFailed': {'en': 'Disabling Tailscale failed', 'it': 'Disattivazione Tailscale fallita'},
    'tailscale.openLink': {'en': 'Open the link to authorize this device',
                           'it': 'Apri il link per autorizzare questo dispositivo'},
    'tailscale.enabled': {'en': 'Tailscale enabled', 'it': 'Tailscale attivato'},
    'tailscale.enabling': {'en': 'Enabling Tailscale…', 'it': 'Attivazione Tailscale in corso…'},
    'tailscale.disabled': {'en': 'Tailscale disabled', 'it': 'Tailscale disattivato'},

    # ── Mouse pointer / misc preferences ────────────────────────────
    'prefs.saveFailed': {'en': 'Could not save the preference', 'it': 'Impossibile salvare la preferenza'},
    'pointer.shown': {'en': 'Mouse pointer shown', 'it': 'Puntatore mouse attivato'},
    'pointer.hidden': {'en': 'Mouse pointer hidden', 'it': 'Puntatore mouse disattivato'},

    # ── Display mode (GUI / headless) ───────────────────────────────
    'displayMode.invalid': {'en': 'Invalid mode', 'it': 'Modalità non valida'},
    'update.inProgressRetry': {'en': 'Update in progress — try again once it finishes',
                               'it': 'Aggiornamento in corso — riprova a fine aggiornamento'},
    'displayMode.changeFailed': {'en': 'Mode change failed', 'it': 'Cambio modalità fallito'},
    'displayMode.guiEnabled': {'en': 'Screen mode enabled', 'it': 'Modalità con schermo attivata'},
    'displayMode.headlessEnabled': {'en': 'Headless mode enabled — the screen will turn off',
                                    'it': 'Modalità headless attivata — lo schermo verrà spento'},

    # ── UI render resolution ────────────────────────────────────────
    'uiResolution.invalid': {'en': 'Invalid resolution', 'it': 'Risoluzione non valida'},
    'uiResolution.unavailable': {'en': 'Feature not available on this system version',
                                 'it': 'Funzione non disponibile su questa versione di sistema'},
    'uiResolution.changeFailed': {'en': 'Resolution change failed', 'it': 'Cambio risoluzione fallito'},
    'uiResolution.updated': {'en': 'Resolution updated — the interface is restarting',
                             'it': "Risoluzione aggiornata — l'interfaccia si riavvia"},

    # ── Provisioning / factory reset / web-admin credential reset ──
    'provisioning.notActive': {'en': 'Provisioning is not active', 'it': 'Provisioning non attivo'},
    'factoryReset.scriptMissing': {'en': 'Reset script not available',
                                   'it': 'Script di ripristino non disponibile'},
    'factoryReset.started': {'en': 'Factory reset started — the device will reboot',
                             'it': 'Ripristino di fabbrica avviato — il dispositivo si riavvierà'},
    'factoryReset.startFailed': {'en': 'Could not start the reset', 'it': 'Avvio ripristino fallito'},
    'webui.credsReset': {'en': 'Web interface credentials cleared',
                         'it': 'Credenziali interfaccia web azzerate'},
    'webui.credsResetFailed': {'en': 'Credential reset failed', 'it': 'Reset credenziali fallito'},

    # ── Tidal Connect ────────────────────────────────────────────────
    'tidal.notInstalled': {'en': 'Tidal Connect is not installed on this device',
                           'it': 'Tidal Connect non installato su questo dispositivo'},
    'tidal.opFailed': {'en': 'Tidal Connect operation failed', 'it': 'Operazione Tidal Connect fallita'},
    'tidal.enabled': {'en': 'Tidal Connect enabled', 'it': 'Tidal Connect abilitato'},
    'tidal.disabled': {'en': 'Tidal Connect disabled', 'it': 'Tidal Connect disabilitato'},

    # ── DSP engine ───────────────────────────────────────────────────
    'dsp.unavailable': {'en': 'DSP is not available on this device', 'it': 'DSP non disponibile su questo dispositivo'},
    'dsp.opFailed': {'en': 'DSP operation failed', 'it': 'Operazione DSP fallita'},
    'dsp.enabled': {'en': 'DSP enabled', 'it': 'DSP attivato'},
    'dsp.disabled': {'en': 'DSP disabled', 'it': 'DSP disattivato'},

    # ── DSP presets ──────────────────────────────────────────────────
    'dspPreset.invalidName': {'en': 'Invalid preset name', 'it': 'Nome preset non valido'},
    'dspPreset.maxReached': {'en': 'Maximum number of presets reached',
                             'it': 'Numero massimo di preset raggiunto'},
    'dspPreset.saveFailed': {'en': 'Saving the preset failed', 'it': 'Salvataggio preset fallito'},
    'dspPreset.saved': {'en': 'Preset saved', 'it': 'Preset salvato'},
    'dspPreset.notFound': {'en': 'Preset not found', 'it': 'Preset non trovato'},
    'dspPreset.loaded': {'en': 'Preset loaded', 'it': 'Preset caricato'},
    'dspPreset.nameExists': {'en': 'A preset with this name already exists',
                             'it': 'Esiste già un preset con questo nome'},
    'dspPreset.renameFailed': {'en': 'Renaming the preset failed', 'it': 'Rinomina preset fallita'},
    'dspPreset.renamed': {'en': 'Preset renamed', 'it': 'Preset rinominato'},
    'dspPreset.deleteFailed': {'en': 'Deleting the preset failed', 'it': 'Eliminazione preset fallita'},
    'dspPreset.deleted': {'en': 'Preset deleted', 'it': 'Preset eliminato'},

    # ── Bluetooth ────────────────────────────────────────────────────
    'bluetooth.unavailableUpdate': {'en': 'Bluetooth is not available: update the system',
                                    'it': 'Bluetooth non disponibile: aggiorna il sistema'},
    'bluetooth.opFailed': {'en': 'Bluetooth operation failed', 'it': 'Operazione Bluetooth fallita'},
    'bluetooth.enabled': {'en': 'Bluetooth enabled', 'it': 'Bluetooth abilitato'},
    'bluetooth.disabled': {'en': 'Bluetooth disabled', 'it': 'Bluetooth disabilitato'},
    'bluetooth.unavailable': {'en': 'Bluetooth is not available', 'it': 'Bluetooth non disponibile'},
    'bluetooth.cannotMakeVisible': {'en': 'Could not make the device visible',
                                    'it': 'Impossibile rendere visibile il dispositivo'},
    'bluetooth.visibleFor2Min': {'en': 'Device visible for 2 minutes', 'it': 'Dispositivo visibile per 2 minuti'},
    'bluetooth.invalidAddress': {'en': 'Invalid Bluetooth address', 'it': 'Indirizzo Bluetooth non valido'},
    'bluetooth.deviceNotFound': {'en': 'Device not found', 'it': 'Dispositivo non trovato'},
    'bluetooth.forgetFailed': {'en': 'Operation failed', 'it': 'Operazione fallita'},
    'bluetooth.forgotten': {'en': 'Device forgotten', 'it': 'Dispositivo dimenticato'},

    # ── OTA channel ──────────────────────────────────────────────────
    'ota.invalidChannel': {'en': 'Invalid channel', 'it': 'Canale non valido'},
    'ota.channelSaveFailed': {'en': 'Could not save the channel', 'it': 'Impossibile salvare il canale'},

    # ── OTA updates (UI / system / OS) + the multi-component sequencer ─
    'update.checkFailed': {'en': 'Update check failed', 'it': 'Controllo aggiornamenti fallito'},
    'update.noneAvailable': {'en': 'No update available', 'it': 'Nessun aggiornamento disponibile'},
    'update.noneAvailableOs': {'en': 'No OS update available', 'it': 'Nessun aggiornamento OS disponibile'},
    'update.checksumMissing': {'en': 'Checksum (.sha256) missing from the release',
                               'it': 'Checksum (.sha256) mancante nella release'},
    'update.checksumReadFailed': {'en': 'Reading the checksum failed', 'it': 'Lettura checksum fallita'},
    'update.checksumEmpty': {'en': 'Checksum is empty', 'it': 'Checksum vuoto'},
    'update.sigMissing': {'en': 'Signature (.sha256.sig) missing: OS update refused',
                          'it': 'Firma (.sha256.sig) mancante: aggiornamento OS rifiutato'},
    'update.startFailed': {'en': 'Starting the update failed', 'it': 'Avvio aggiornamento fallito'},
    'update.alreadyInProgress': {'en': 'Update already in progress', 'it': 'Aggiornamento già in corso'},
    'update.planSaveFailed': {'en': 'Saving the update plan failed', 'it': 'Salvataggio del piano fallito'},
    'update.inProgress': {'en': 'Update in progress', 'it': 'Aggiornamento in corso'},

    # ── Disk install (bare-metal installer) + guided room correction ──
    'install.enumFailed': {'en': 'Disk enumeration failed', 'it': 'Enumerazione dischi fallita'},
    'install.invalidDisk': {'en': 'Invalid disk', 'it': 'Disco non valido'},
    'install.cannotInstallOnBootMedia': {'en': 'Cannot install on the boot medium',
                                         'it': 'Non è possibile installare sul supporto di avvio'},
    'install.systemdRunNoResponse': {'en': 'systemd-run did not respond',
                                     'it': 'systemd-run non ha risposto'},
    'common.starting': {'en': 'Starting…', 'it': 'Avvio…'},
    'roomcorr.updateRequired': {'en': 'A system update is required', 'it': 'Aggiornamento di sistema richiesto'},
    'roomcorr.micNotFound': {'en': 'Microphone not found: connect a USB mic',
                             'it': 'Microfono non trovato: collega un mic USB'},
    'roomcorr.alreadyMeasuring': {'en': 'A measurement is already in progress', 'it': 'Misura già in corso'},
    'roomcorr.noFilter': {'en': 'No filter present: run the measurement first',
                          'it': 'Nessun filtro presente: esegui prima la misura'},

    # ── Lyrion Music Server updates ─────────────────────────────────
    'lyrion.badChannel': {'en': 'Unknown channel.', 'it': 'Canale sconosciuto.'},
    'lyrion.channelSaveFailed': {'en': 'Could not save the channel.', 'it': 'Impossibile salvare il canale.'},
    'lyrion.checkFailed': {'en': 'Could not check for Lyrion updates.',
                           'it': 'Impossibile controllare gli aggiornamenti di Lyrion.'},
    'lyrion.noBuildFound': {'en': 'No Lyrion build found on the download server.',
                            'it': 'Nessuna build di Lyrion trovata sul server di download.'},
    'lyrion.upToDate': {'en': 'Lyrion Music Server is already up to date.',
                        'it': 'Lyrion Music Server è già aggiornato.'},
    'lyrion.startFailed': {'en': 'Could not start the update.', 'it': "Impossibile avviare l'aggiornamento."},

    # ── sources_server.py: applying sources to Lyrion prefs ─────────
    'lyrion.yamlMissing': {'en': 'python3-yaml is not installed', 'it': 'python3-yaml non installato'},
    'lyrion.prefsNotFound': {'en': 'Lyrion prefs file not found. Check that Lyrion is running '
                                    '(systemctl status lyrionmusicserver).',
                             'it': 'File prefs di Lyrion non trovato. Verifica che Lyrion sia avviato '
                                   '(systemctl status lyrionmusicserver).'},
    'lyrion.diskNotMounted': {'en': 'Disk not mounted: {disks}. Check the connection before applying.',
                              'it': 'Disco non montato: {disks}. Verifica il collegamento prima di applicare.'},
    'lyrion.applied': {'en': '{count} source(s) applied. Lyrion restarted and scanning.',
                       'it': '{count} sorgenti applicate. Lyrion riavviato e in scansione.'},

    # ── sources_server.py: backup creation ──────────────────────────
    'backup.systemUpdateRequired': {'en': 'A system update is required',
                                    'it': 'Aggiornamento di sistema richiesto'},
    'backup.alreadyInProgress': {'en': 'A backup is already in progress', 'it': 'Backup già in corso'},
    'restore.alreadyInProgress': {'en': 'A restore is already in progress', 'it': 'Ripristino già in corso'},

    # ── webui_server.py: api_server proxy unreachable ───────────────
    'proxy.serviceUnavailable': {'en': 'Service unavailable', 'it': 'Servizio non disponibile'},
    'proxy.serviceUnreachable': {'en': 'Service unreachable', 'it': 'Servizio non raggiungibile'},
    'auth.required': {'en': 'Authentication required', 'it': 'Autenticazione richiesta'},
    'auth.accountExists': {'en': 'Account already exists', 'it': 'Account già esistente'},
    'provision.invalidMode': {'en': 'Invalid mode', 'it': 'Modalità non valida'},
    'provision.modeAlreadyClaimed': {'en': 'Mode already claimed', 'it': 'Modalità già scelta'},
    'auth.wrongPassword': {'en': 'Wrong password', 'it': 'Password non valida'},
    'network.scanFailed': {'en': 'Wi-Fi scan failed', 'it': 'Scansione WiFi fallita'},
    'audio.listDevicesFailed': {'en': 'Reading audio devices failed', 'it': 'Lettura dispositivi audio fallita'},
    'tailscale.statusUnavailable': {'en': 'Status unavailable', 'it': 'Stato non disponibile'},
    'tidal.statusUnavailable': {'en': 'Tidal Connect status unavailable', 'it': 'Stato Tidal Connect non disponibile'},
    'bluetooth.statusUnavailable': {'en': 'Bluetooth status unavailable', 'it': 'Stato Bluetooth non disponibile'},
    'network.hotspotUnsupported': {'en': "This Wi-Fi card doesn't support hotspot mode",
                                   'it': 'La scheda Wi-Fi non supporta la modalità hotspot'},
    'auth.csrfInvalid': {'en': 'Missing or invalid CSRF token', 'it': 'CSRF token mancante o non valido'},
    'auth.invalidCredentials': {'en': 'Invalid credentials', 'it': 'Credenziali non valide'},
    'provision.notInProgress': {'en': 'Not in provisioning', 'it': 'Non in provisioning'},
    'provision.notInstaller': {'en': 'Not booted from the installer', 'it': "Non avviato dall'installer"},
    'proxy.endpointNotAllowed': {'en': 'Endpoint not allowed', 'it': 'Endpoint non consentito'},
    'proxy.unknownEndpoint': {'en': 'Unknown endpoint', 'it': 'Endpoint sconosciuto'},
    'pairing.tokenInvalid': {'en': 'Missing or invalid pairing token', 'it': 'Token di pairing mancante o non valido'},
    # ── Timezone ───────────────────────────────────────────────────
    'timezone.invalid': {'en': 'Unknown timezone', 'it': 'Fuso orario sconosciuto'},
    'timezone.changeFailed': {'en': 'Could not change the timezone', 'it': 'Cambio fuso orario fallito'},
    'timezone.updated': {'en': 'Timezone set to {tz}', 'it': 'Fuso orario impostato su {tz}'},

    # ── Virtual keyboard (on-screen keyboard helper) ─────────────────
    'keyboard.started': {'en': 'Virtual keyboard {cmd} started', 'it': 'Tastiera virtuale {cmd} avviata'},
    'keyboard.noneFound': {'en': 'No system virtual keyboard found. Install onboard, florence, xvkbd or matchbox-keyboard',
                           'it': 'Nessuna tastiera virtuale di sistema trovata. Installa onboard, florence, xvkbd o matchbox-keyboard'},
    'keyboard.startFailed': {'en': 'Could not start the virtual keyboard', 'it': "Errore nell'avvio della tastiera virtuale"},
    'keyboard.closed': {'en': 'Virtual keyboard closed', 'it': 'Tastiera virtuale chiusa'},
    'keyboard.closeFailed': {'en': 'Could not close the virtual keyboard', 'it': 'Errore nella chiusura della tastiera virtuale'},
}


def t(code, lang, **variables):
    """Translate `code` into `lang` ('en' or 'it'), with {placeholder}
    interpolation via `variables`. Falls back to English when `lang` isn't
    supported or the specific translation is missing, and to the bare code
    string when the code itself is unknown — this never raises, so a typo'd
    or not-yet-added code degrades to a readable-enough fallback instead of
    crashing the request that was trying to report an error."""
    entry = MESSAGES.get(code)
    if not entry:
        return code
    text = entry.get(lang) or entry.get('en') or code
    if variables:
        try:
            text = text.format(**variables)
        except (KeyError, IndexError):
            pass
    return text
