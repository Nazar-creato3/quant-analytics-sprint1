"use client";

import { useEffect, useState } from "react";
import { X, Share, Plus } from "lucide-react";

const DISMISS_KEY = "qa-pwa-install-dismissed";

function isIos(): boolean {
  if (typeof navigator === "undefined") return false;
  return /iPad|iPhone|iPod/.test(navigator.userAgent);
}

function isStandalone(): boolean {
  if (typeof window === "undefined") return false;
  return (
    window.matchMedia("(display-mode: standalone)").matches ||
    (window.navigator as Navigator & { standalone?: boolean }).standalone === true
  );
}

export function PwaInstallPrompt() {
  const [visible, setVisible] = useState(false);
  const [deferredPrompt, setDeferredPrompt] = useState<{ prompt: () => Promise<void> } | null>(
    null,
  );

  useEffect(() => {
    if (typeof window === "undefined") return;
    if (isStandalone()) return;
    if (localStorage.getItem(DISMISS_KEY) === "1") return;

    const handler = (e: Event) => {
      e.preventDefault();
      setDeferredPrompt({ prompt: () => (e as BeforeInstallPromptEvent).prompt() });
      setVisible(true);
    };
    window.addEventListener("beforeinstallprompt", handler);

    if (isIos()) {
      const timer = setTimeout(() => setVisible(true), 3000);
      return () => {
        clearTimeout(timer);
        window.removeEventListener("beforeinstallprompt", handler);
      };
    }

    return () => window.removeEventListener("beforeinstallprompt", handler);
  }, []);

  const dismiss = () => {
    localStorage.setItem(DISMISS_KEY, "1");
    setVisible(false);
  };

  const install = async () => {
    if (deferredPrompt) {
      await deferredPrompt.prompt();
      dismiss();
    }
  };

  if (!visible) return null;

  return (
    <div className="fixed bottom-16 md:bottom-4 inset-x-4 z-[60] max-w-md mx-auto">
      <div className="rounded-xl border border-terminal-accent/30 bg-cockpit-panel p-4 shadow-xl">
        <div className="flex items-start justify-between gap-2 mb-2">
          <p className="text-sm font-semibold text-white">Установить Quant Analytics</p>
          <button type="button" onClick={dismiss} className="p-1 text-qa-muted min-w-[44px] min-h-[44px] flex items-center justify-center" aria-label="Dismiss">
            <X size={16} />
          </button>
        </div>
        {isIos() ? (
          <div className="text-xs text-qa-muted space-y-2">
            <p>На iOS push-уведомления работают только после добавления на Home Screen:</p>
            <ol className="list-decimal pl-4 space-y-1">
              <li className="flex items-center gap-1">
                Нажмите <Share size={12} className="inline text-terminal-accent" /> «Поделиться»
              </li>
              <li className="flex items-center gap-1">
                Выберите <Plus size={12} className="inline text-terminal-accent" /> «На экран Домой»
              </li>
            </ol>
          </div>
        ) : (
          <div className="space-y-3">
            <p className="text-xs text-qa-muted">
              Установите приложение для быстрого доступа и offline shell.
            </p>
            {deferredPrompt && (
              <button
                type="button"
                onClick={install}
                className="w-full min-h-[44px] rounded-lg bg-terminal-accent text-black font-semibold text-sm"
              >
                Установить
              </button>
            )}
          </div>
        )}
      </div>
    </div>
  );
}

interface BeforeInstallPromptEvent extends Event {
  prompt: () => Promise<void>;
}
