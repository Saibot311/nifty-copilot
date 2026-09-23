"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";
import { subscribeToTick } from "@/lib/api";

/** Re-fetches the whole page on a timer.
 *
 *  The dashboard is server-rendered, so without this every section keeps
 *  whatever it was given when the tab was opened — patterns, indicators, the
 *  briefing and the market tab all freeze at page-load time. The header
 *  ticks on its own (LiveTicker); this refreshes the rest.
 *
 *  Every 60s while the market is open, every 15 minutes when it is shut, and
 *  never while the tab is in the background. */
export function AutoRefresh() {
  const router = useRouter();

  useEffect(() => {
    let alive = true;
    let timer: ReturnType<typeof setTimeout>;

    // Market state comes from the shared tick rather than a fetch of its own.
    let open = false;
    const stop = subscribeToTick((t) => { open = !!t.market?.is_open; });

    const tick = () => {
      if (!alive) return;
      if (document.visibilityState === "visible") router.refresh();
      timer = setTimeout(tick, open ? 60_000 : 900_000);
    };

    timer = setTimeout(tick, 60_000);
    return () => { alive = false; clearTimeout(timer); stop(); };
  }, [router]);

  return null;
}
