import React, { useState, useEffect, useRef } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { Disc3, RefreshCw } from 'lucide-react';
import { systemAPI } from '../utils/api';
import { useI18n } from '../i18n';
import WifiConfigPanel from '../components/WifiConfigPanel';

/**
 * First-setup wizard.
 *
 * The network step (this screen's whole job before the box is online) is
 * done entirely on-screen now, via WifiConfigPanel below — there is no
 * setup hotspot/AP any more. It used to raise one so a phone could join it
 * and drive the whole flow (language, network, mode, audio, Lyrion,
 * sources, timezone) through webui_server.py's captive portal, but a
 * single Wi-Fi radio switching between AP and station mode on every join
 * attempt proved unreliable on real hardware (some Wi-Fi cards, e.g. Intel
 * iwlwifi, would time out or fail activation even with a correct password
 * and the network in range) — and device mode (screen vs. headless) isn't
 * even decided until *after* this step, so a screen is always physically
 * available here regardless of what the unit ends up being configured as.
 * Once the network step succeeds (here, or via Ethernet), the remaining
 * steps still happen from a phone/browser on the box's real address — see
 * the "connected" branch below.
 */
const SetupWizard = ({ onComplete }) => {
  const { t } = useI18n();
  const [stage, setStage] = useState(null);
  const [provisionError, setProvisionError] = useState(null);
  const [networks, setNetworks] = useState([]);
  const [wired, setWired] = useState(false);
  const [deviceIp, setDeviceIp] = useState(null);
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
          setStage(res.data.stage || null);
          setProvisionError(res.data.error || null);
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
    // always unambiguous, so it's what the fallback address should show.
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

  useEffect(() => {
    if (stage === 'connecting' || stage === 'network-ok' || stage === 'failed') setWifiSubmitting(false);
  }, [stage]);

  const isConnected = wired || stage === 'network-ok';

  // Manual "refresh now" — the server also rescans on its own every ~20s
  // while waiting (see _evaluate_provisioning() in webui_server.py), this
  // just gives the owner an immediate result instead of waiting for that
  // tick. No AP to juggle any more, so it's just a plain scan.
  const rescan = async () => {
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
          {isConnected ? (
            <>
              <h1 className="text-2xl font-bold text-white mb-2">{t('wizard.qr.connectedTitle')}</h1>
              <p className="text-hifi-silver/70 text-sm leading-relaxed mb-8">{t('wizard.qr.connectedSubtitle')}</p>
            </>
          ) : (
            <>
              <h1 className="text-2xl font-bold text-white mb-2">{t('wizard.wifi.title')}</h1>
              <p className="text-hifi-silver/70 text-sm leading-relaxed mb-6">{t('wizard.wifi.setupSubtitle')}</p>
            </>
          )}

          {isConnected && (
            // Either the box is already on a real network (wired, or Wi-Fi
            // just configured below), or nothing back from the poll yet
            // (first few seconds after boot): both cases fall back to the
            // same LAN address. Prefer the device's own IP over
            // hifiplayer.local: the hostname is ambiguous the moment more
            // than one Osmium Sound unit is on the same network (mDNS
            // answers with whichever responds first), the IP never is.
            <>
              <div className="inline-flex flex-col items-center bg-white rounded-2xl px-8 py-6">
                <span className="text-black/50 text-xs font-semibold uppercase tracking-wide">{t('wizard.qr.addressLabel')}</span>
                <span className="text-black text-2xl font-bold font-mono mt-1">
                  {deviceIp ? `http://${deviceIp}` : 'http://hifiplayer.local'}
                </span>
              </div>
              {/* Safari assumes https:// for a bare IP typed into the address
                  bar; this device only serves plain http://, so that guess
                  fails with a "can't connect to server" error, not a page —
                  spell out that http:// is mandatory, not decorative. Sized
                  and colored to actually be noticed, not a fine-print
                  afterthought under the address box. */}
              <div className="mt-4 max-w-xs rounded-xl border border-hifi-gold/30 bg-hifi-gold/10 px-4 py-3 text-left space-y-1.5">
                <p className="text-hifi-gold text-xs font-bold uppercase tracking-wide">{t('wizard.qr.tipsLabel')}</p>
                <p className="text-white/90 text-sm leading-snug">{t('wizard.qr.addressHint')}</p>
                <p className="text-white/90 text-sm leading-snug">{t('wizard.qr.pcRecommended')}</p>
              </div>
            </>
          )}
        </motion.div>

        {!isConnected && (
          <div className="w-full max-w-sm mt-2">
            <WifiConfigPanel
              inline
              networks={networks}
              scanning={wifiRescanning || (networks.length === 0 && !wifiSubmitError && !provisionError)}
              connecting={wifiSubmitting || stage === 'connecting'}
              error={wifiSubmitError || (stage === 'failed' ? provisionError : null)}
              onConnect={handleWifiConnect}
            />
            <button onClick={rescan} disabled={wifiRescanning}
              className="mt-3 mx-auto flex items-center gap-1.5 text-sm text-hifi-silver/70 hover:text-hifi-silver disabled:opacity-40">
              <RefreshCw size={13} className={wifiRescanning ? 'animate-spin' : ''} />
              {t('wizard.wifi.rescan')}
            </button>
          </div>
        )}
      </motion.div>
    </AnimatePresence>
  );
};

export default SetupWizard;
