import React, { useEffect, useRef, useState } from 'react';
import jsQR from 'jsqr';
import { X } from 'lucide-react';
import { useI18n } from '../../i18n';

// Camera-based QR scanner for the appliance's existing "Phone control" QR
// (Settings.jsx, JSON payload { lms, api, token }) — the same QR the Android
// companion app scans. Decodes frames off a hidden <canvas> at ~10fps via
// jsQR (no BarcodeDetector dependency, works on older Safari/iOS too).
const QrScanner = ({ onDecode, onClose }) => {
  const { t } = useI18n();
  const videoRef = useRef(null);
  const canvasRef = useRef(null);
  const streamRef = useRef(null);
  const rafRef = useRef(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    let cancelled = false;

    navigator.mediaDevices?.getUserMedia?.({ video: { facingMode: 'environment' } })
      .then((stream) => {
        if (cancelled) { stream.getTracks().forEach((t) => t.stop()); return; }
        streamRef.current = stream;
        const video = videoRef.current;
        video.srcObject = stream;
        video.setAttribute('playsinline', 'true');
        video.play();
        video.onloadedmetadata = () => tick();
      })
      .catch(() => setError(t('qrScanner.cameraDenied')));

    const tick = () => {
      const video = videoRef.current;
      const canvas = canvasRef.current;
      if (!video || !canvas || video.readyState !== video.HAVE_ENOUGH_DATA) {
        rafRef.current = requestAnimationFrame(tick);
        return;
      }
      canvas.width = video.videoWidth;
      canvas.height = video.videoHeight;
      const ctx = canvas.getContext('2d');
      ctx.drawImage(video, 0, 0, canvas.width, canvas.height);
      const frame = ctx.getImageData(0, 0, canvas.width, canvas.height);
      const code = jsQR(frame.data, frame.width, frame.height);
      if (code?.data) {
        onDecode(code.data);
        return; // stop the loop — cleanup effect below tears down the stream
      }
      rafRef.current = requestAnimationFrame(tick);
    };

    return () => {
      cancelled = true;
      if (rafRef.current) cancelAnimationFrame(rafRef.current);
      streamRef.current?.getTracks().forEach((t) => t.stop());
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return (
    <div className="fixed inset-0 z-[100] bg-black flex flex-col">
      <div className="flex items-center justify-between h-12 px-2 shrink-0">
        <span className="text-sm text-white/80 px-2">{t('qrScanner.title')}</span>
        <button onClick={onClose} className="p-2 text-white"><X size={20} /></button>
      </div>
      <div className="flex-1 relative overflow-hidden">
        <video ref={videoRef} className="absolute inset-0 w-full h-full object-cover" muted />
        <canvas ref={canvasRef} className="hidden" />
        <div className="absolute inset-0 flex items-center justify-center pointer-events-none">
          <div className="w-64 h-64 border-2 border-hifi-gold/70" />
        </div>
        {error && (
          <div className="absolute inset-x-6 bottom-10 text-center text-sm text-red-300">
            {error}
          </div>
        )}
      </div>
    </div>
  );
};

export default QrScanner;
