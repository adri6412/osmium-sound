import React, { useState } from 'react';
import { Share, X } from 'lucide-react';
import { useI18n } from '../../i18n';

// iOS gives web pages no API to trigger "Add to Home Screen" themselves —
// the last step is always a manual Share → Add to Home Screen tap by the
// user (a platform restriction, not something any PWA can automate). This
// banner just makes that manual step obvious the first few times the PWA is
// opened in Safari (not yet installed), then stays dismissed.
const DISMISS_KEY = 'hifiAddToHomeDismissed';

const isIosSafariNotStandalone = () =>
  // navigator.standalone is Safari-only: `false` = running in Safari, not
  // installed; `true` = already launched from the home-screen icon;
  // `undefined` = not Safari (Chrome/Firefox on iOS, or not iOS at all).
  typeof window !== 'undefined' && window.navigator.standalone === false;

const AddToHomeBanner = () => {
  const { t } = useI18n();
  const [dismissed, setDismissed] = useState(() => localStorage.getItem(DISMISS_KEY) === '1');

  if (dismissed || !isIosSafariNotStandalone()) return null;

  const dismiss = () => {
    localStorage.setItem(DISMISS_KEY, '1');
    setDismissed(true);
  };

  return (
    <div className="flex items-center gap-2 px-3 py-2 bg-hifi-gold/10 border-b border-hifi-gold/30 shrink-0">
      <Share size={15} className="text-hifi-gold shrink-0" />
      <p className="text-[12px] text-hifi-gold flex-1">{t('addToHome.hint')}</p>
      <button onClick={dismiss} className="p-1 text-hifi-gold/70 shrink-0"><X size={14} /></button>
    </div>
  );
};

export default AddToHomeBanner;
