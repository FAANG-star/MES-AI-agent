"use client";

import { createContext, useCallback, useContext, useEffect, useRef, useState, useSyncExternalStore } from "react";

import {
  deviceZone,
  resolveViewerZone,
  wallClock,
  ZONE_EVENT,
  ZONE_STORAGE_KEY,
  type WallClock,
} from "@/lib/timezone";

interface TimeContext {
  /** The factory's IANA zone — decides what "today" means. Null if the backend is down. */
  factoryZone: string | null;
  /** The viewer's zone — decides how times are shown. Null until the browser has said. */
  viewerZone: string | null;
  /** True when the viewer is following their device rather than a chosen zone. */
  automatic: boolean;
  setViewerZone: (zone: string | null) => void;
  /** The current instant, corrected for any drift between this device and the server. */
  now: Date;
  factoryClock: WallClock | null;
  viewerClock: WallClock | null;
}

const Context = createContext<TimeContext | null>(null);

function readStored(): string | null {
  try {
    return localStorage.getItem(ZONE_STORAGE_KEY);
  } catch {
    return null;
  }
}

function subscribe(onChange: () => void) {
  window.addEventListener(ZONE_EVENT, onChange);
  window.addEventListener("storage", onChange);
  return () => {
    window.removeEventListener(ZONE_EVENT, onChange);
    window.removeEventListener("storage", onChange);
  };
}

/**
 * One clock for the whole page.
 *
 * The first render uses the server's instant, so the server and the browser
 * render identical markup. After that the clock ticks on the device, corrected
 * by the difference measured against the server at load — a laptop whose clock
 * is five minutes fast must not show the factory's time five minutes fast.
 */
export function TimeProvider({
  factoryZone,
  serverNow,
  children,
}: {
  factoryZone: string | null;
  serverNow: string | null;
  children: React.ReactNode;
}) {
  const initial = serverNow ? new Date(serverNow) : new Date(0);
  const [now, setNow] = useState<Date>(initial);
  const skew = useRef(0);

  const stored = useSyncExternalStore(subscribe, readStored, () => undefined);
  const hydrated = stored !== undefined;
  const viewerZone = hydrated ? resolveViewerZone(stored, deviceZone()) : null;
  const automatic = hydrated && resolveViewerZone(stored, "") === "";

  useEffect(() => {
    if (serverNow) skew.current = new Date(serverNow).getTime() - Date.now();
    const tick = () => setNow(new Date(Date.now() + skew.current));
    const first = setTimeout(tick, 0);
    // Wake at the top of each minute: the clocks show minutes, so ticking
    // more often would only repaint the same digits.
    const interval = setInterval(tick, 15_000);
    return () => {
      clearTimeout(first);
      clearInterval(interval);
    };
  }, [serverNow]);

  const setViewerZone = useCallback((zone: string | null) => {
    try {
      if (zone) localStorage.setItem(ZONE_STORAGE_KEY, zone);
      else localStorage.removeItem(ZONE_STORAGE_KEY);
    } catch {
      // Storage refused: nothing to persist, and nothing else to do.
    }
    window.dispatchEvent(new Event(ZONE_EVENT));
  }, []);

  const value: TimeContext = {
    factoryZone,
    viewerZone,
    automatic,
    setViewerZone,
    now,
    factoryClock: factoryZone && serverNow ? wallClock(now, factoryZone) : null,
    viewerClock: viewerZone && serverNow ? wallClock(now, viewerZone) : null,
  };

  return <Context.Provider value={value}>{children}</Context.Provider>;
}

export function useTime(): TimeContext {
  const value = useContext(Context);
  if (!value) throw new Error("useTime must be used inside <TimeProvider>");
  return value;
}
