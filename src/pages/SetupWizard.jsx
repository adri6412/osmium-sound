import React, { useState, useEffect, useRef } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { QRCodeSVG } from 'qrcode.react';
import { Disc3 } from 'lucide-react';
import { systemAPI } from '../utils/api';
import { useI18n } from '../i18n';
import WifiConfigPanel from '../components/WifiConfigPanel';

/**
 * First-setup wizard.
 *
 * No mouse/keyboard/touch is required: the screen's only job is to display
 * branding and the setup hotspot's Wi-Fi QR code the instant it boots, then
 * wait. Every actual setup step (language, restore-from-backup, network,
 * device mode, audio, Lyrion, sources, timezone) happens on a phone/browser
 * connected to that hotspot, served by webui_server.py's captive portal —
 * see SETUP_CAPTIVE_HTML there. This component only polls provisioning
 * status and reacts once the phone side finishes (`finalize`).
 *
 * The one thing that CAN be done straight from this screen is the network
 * step itself (WifiConfigPanel below) — a touch-only escape hatch for
 * whoever doesn't have a phone handy, using the same provisioning API the
 * captive portal's network step uses.
 */
const SetupWizard = ({ onComplete }) => {
  const { t } = useI18n();
  const [apInfo, setApInfo] = useState(null); // { ssid, psk, active, error } from provision status
  const [stage, setStage] = useState(null);
  const [networks, setNetworks] = useState([]);
  const [wired, setWired] = useState(false);
  const [deviceIp, setDeviceIp] = useState(null);
  const [showWifiPanel, setShowWifiPanel] = useState(false);
  const [wifiRescanning, setWifiRescanning] = useState(false);
  const [wifiSubmitting, setWifiSubmitting] = useState(false);
  const [wifiSubmitError, setWifiSubmitError] = useState(null);
  const doneRef = useRef(false);

  useEffect(() => {
    let alive = true;
    const poll = async () => {
      if (doneRef.current) return;
      try {
        const res = await systemAPI.getProvisionStatus();
        if (!alive) return;
        if (res.success && res.data) {
          if (res.data.ap) setApInfo(res.data.ap);
          setStage(res.data.stage || null);
          setNetworks(res.data.networks || []);
          setWired(!!res.data.wired);
          // The phone finished setup (claim_mode + finalize already ran
          // server-side) — pick up and move on. No button, no local step.
          //
          // `pending: false` alone isn't enough: api_server.py's
          // get_provision_status() also returns bare `{pending: false}`
          // (no `completed` key) whenever hifi-webui itself is transiently
          // unreachable -- e.g. right after a mid-wizard reboot (a
          // system-component update restarts that very service), a window
          // this poll starts hitting the instant Electron comes back up,
          // well before hifi-webui has finished starting. Without the
          // `completed` check that blip reads as "setup finished" and
          // permanently jumps to the real app mid-wizard (see App.jsx's own
          // provisioning check, which already guards on both fields).
          if (res.data.pending === false && res.data.completed === true) {
            doneRef.current = true;
            localStorage.setItem('firstSetupComplete', 'true');
            onComplete?.();
          }
        }
      } catch (_) {}
    };
    poll();
    const id = setInterval(poll, 3000);

    // The device's own IP, not just the hostname: hifiplayer.local is
    // ambiguous the moment more than one Osmium Sound unit is on the same
    // network (mDNS resolves to whichever one answers first) — the IP is
    // always unambiguous, so it's what the fallback QR should encode.
    const pollIp = async () => {
      try {
        const res = await systemAPI.getNetworkStatus();
        if (alive && res.success && res.data?.ip) { setDeviceIp(res.data.ip); return; }
        const info = await systemAPI.getSystemInfo();
        if (alive && info.success && info.data?.local_ip && info.data.local_ip !== 'Unknown') {
          setDeviceIp(info.data.local_ip);
        }
      } catch (_) {}
    };
    pollIp();
    const ipId = setInterval(pollIp, 5000);

    return () => { alive = false; clearInterval(id); clearInterval(ipId); };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Once the box is on a real network (either the phone drove it, or the
  // panel below did), close the panel if it's still open and let the normal
  // render fall through to the "open on your phone" QR.
  useEffect(() => {
    if (stage === 'network-ok') setShowWifiPanel(false);
    if (stage === 'connecting' || stage === 'network-ok' || stage === 'failed') setWifiSubmitting(false);
  }, [stage]);

  const isConnected = wired || stage === 'network-ok';

  // The passive `networks` list is a single scan taken before the hotspot
  // first came up (this device's one Wi-Fi radio can't scan while it's also
  // the AP — see _scan_wifi()/_evaluate_provisioning() in webui_server.py).
  // Opening the panel is the one moment the owner is looking at the screen
  // instead of their phone, so it's worth briefly trading the hotspot for a
  // genuinely live scan: drop it, scan, raise it back (provisionWifiRescan
  // on the server does all three under one lock) — takes a few seconds.
  const openWifiPanel = async () => {
    setShowWifiPanel(true);
    setWifiRescanning(true);
    try {
      const res = await systemAPI.provisionWifiRescan();
      if (res.success && Array.isArray(res.data?.networks)) setNetworks(res.data.networks);
    } catch (_) {}
    setWifiRescanning(false);
  };

  const handleWifiConnect = async (ssid, password) => {
    setWifiSubmitError(null);
    setWifiSubmitting(true);
    try {
      const res = await systemAPI.provisionWifiConnect(ssid, password);
      // On success the box's own state machine takes over (stage moves
      // 'connecting' -> 'network-ok'/'failed', picked up by the poll above);
      // only a same-tick rejection (e.g. provisioning already finished)
      // needs to be shown here directly.
      if (!res.success) {
        setWifiSubmitError(res.message || t('wizard.wifi.connectFailed'));
        setWifiSubmitting(false);
      }
    } catch (_) {
      setWifiSubmitError(t('wizard.wifi.connectFailed'));
      setWifiSubmitting(false);
    }
  };

  return (
    <AnimatePresence>
      <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} transition={{ duration: 0.2 }}
        className="absolute inset-0 z-[60] bg-hifi-dark flex flex-col items-center justify-center font-display overflow-hidden px-8">
        <motion.div initial={{ scale: 0.9, opacity: 0 }} animate={{ scale: 1, opacity: 1 }} transition={{ delay: 0.1 }}
          className="flex flex-col items-center text-center max-w-md">
          <div className="w-16 h-16 rounded-2xl bg-gradient-to-br from-hifi-gold to-yellow-600 flex items-center justify-center shadow-[0_0_40px_rgba(212,175,55,0.3)] mb-6">
            <Disc3 size={32} className="text-black" />
          </div>
          {apInfo?.error && !isConnected ? (
            <>
              <h1 className="text-2xl font-bold text-white mb-2">{t('wizard.qr.errorTitle')}</h1>
              <p className="text-hifi-silver/70 text-sm leading-relaxed mb-8">{apInfo.error}</p>
            </>
          ) : isConnected ? (
            <>
              <h1 className="text-2xl font-bold text-white mb-2">{t('wizard.qr.connectedTitle')}</h1>
              <p className="text-hifi-silver/70 text-sm leading-relaxed mb-8">{t('wizard.qr.connectedSubtitle')}</p>
            </>
          ) : (
            <>
              <h1 className="text-2xl font-bold text-white mb-2">{t('wizard.qr.title')}</h1>
              <p className="text-hifi-silver/70 text-sm leading-relaxed mb-8">{t('wizard.qr.subtitle')}</p>
            </>
          )}

          {apInfo?.ssid && apInfo?.active && !isConnected ? (
            <div className="inline-flex flex-col items-center bg-white rounded-2xl p-4">
              <QRCodeSVG value={`WIFI:T:nopass;S:${apInfo.ssid};;`} size={180} />
              <span className="text-black text-xs font-semibold mt-2">{apInfo.ssid}</span>
            </div>
          ) : apInfo?.error && !isConnected ? (
            // Hotspot failed to come up and there's no LAN fallback either —
            // a QR here would point at a network the phone can't reach, so
            // show nothing and let the error message above stand.
            null
          ) : (
            // Either the box is already on a real network (wired, or Wi-Fi
            // configured via the phone or the on-screen panel below), or
            // nothing back from the poll yet (first few seconds after boot):
            // both cases fall back to the same LAN/URL QR. Prefer the
            // device's own IP over hifiplayer.local: the hostname is
            // ambiguous the moment more than one Osmium Sound unit is on the
            // same network (mDNS answers with whichever responds first), the
            // IP never is.
            <div className="inline-flex flex-col items-center bg-white rounded-2xl p-4">
              <QRCodeSVG value={`http://${deviceIp || 'hifiplayer.local'}`} size={180} />
              <span className="text-black text-xs mt-2">
                {deviceIp ? `http://${deviceIp}` : 'http://hifiplayer.local'}
              </span>
              {deviceIp && <span className="text-black/50 text-[10px] mt-0.5">http://hifiplayer.local</span>}
            </div>
          )}

          {!isConnected && (
            <button onClick={openWifiPanel}
              className="mt-4 text-sm text-hifi-silver/70 hover:text-hifi-silver underline underline-offset-2">
              {t('wizard.qr.manualButton')}
            </button>
          )}
        </motion.div>

        {showWifiPanel && (
          <WifiConfigPanel
            networks={networks}
            // Live while openWifiPanel's rescan is in flight; otherwise fall
            // back to "hasn't reported back yet" vs. a real empty result the
            // same way as before the AP was ever confirmed up.
            scanning={wifiRescanning || (!isConnected && !apInfo?.active && !apInfo?.error && networks.length === 0)}
            connecting={wifiSubmitting || stage === 'connecting'}
            error={wifiSubmitError || (stage === 'failed' ? apInfo?.error : null)}
            onConnect={handleWifiConnect}
            onClose={() => setShowWifiPanel(false)}
          />
        )}
      </motion.div>
    </AnimatePresence>
  );
};

export default SetupWizard;
