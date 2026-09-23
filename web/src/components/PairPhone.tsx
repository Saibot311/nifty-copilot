"use client";

import { useEffect, useState } from "react";
import Image from "next/image";
import QRCode from "qrcode";
import { fetchPairing, journalRequest, type Pairing } from "@/lib/api";
import { Panel } from "./ui";

/** Pairing, shown on the Mac only.
 *
 *  The API refuses this to anything but localhost, so a phone can never
 *  fetch the token — it can only receive it by scanning the code on your
 *  screen. Nothing here is logged, and the code is drawn in this browser
 *  rather than sent to any QR service. */
export function PairPhone() {
  const [pairing, setPairing] = useState<Pairing | null>(null);
  const [qr, setQr] = useState<string | null>(null);
  const [shown, setShown] = useState(false);
  const [note, setNote] = useState<string | null>(null);

  useEffect(() => {
    if (!shown) return;
    let alive = true;
    fetchPairing().then(async (r) => {
      if (!alive || !r.data) return;
      setPairing(r.data);
      const link = r.data.links[0];
      if (link) {
        setQr(await QRCode.toDataURL(link, {
          margin: 1, width: 320, color: { dark: "#e4e4e7", light: "#09090b" },
        }));
      }
    });
    return () => { alive = false; };
  }, [shown]);

  async function rotate() {
    const r = await journalRequest<{ note: string }>("/api/access/rotate", "POST", {});
    setNote(r.data?.note ?? r.error ?? null);
    setPairing(null);
    setQr(null);
    setShown(false);
  }

  if (!shown) {
    return (
      <button
        type="button"
        onClick={() => setShown(true)}
        className="rounded-md border border-zinc-700 px-3 py-1.5 text-xs text-zinc-300 hover:border-indigo-500/60 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-indigo-500/60"
      >
        Use this on my phone
      </button>
    );
  }

  return (
    <Panel className="w-full p-4">
      {pairing?.exposed === false && (
        <p className="mb-3 rounded-lg border border-amber-500/30 bg-amber-500/[0.06] px-3 py-2 text-xs text-amber-200">
          The dashboard is only listening to this Mac, so a phone cannot reach it yet. In Terminal, run
          <code className="mx-1 rounded bg-zinc-950 px-1.5 py-0.5 text-[11px]">./scripts/install_app_services.sh --lan</code>
          then come back here.
        </p>
      )}
      <div className="flex flex-wrap items-start gap-5">
        {qr ? (
          <Image src={qr} alt="Pairing code for your phone" width={160} height={160} unoptimized className="rounded-lg" />
        ) : (
          <div className="h-40 w-40 animate-pulse rounded-lg bg-zinc-800/60" />
        )}
        <div className="min-w-[14rem] flex-1 text-xs leading-relaxed text-zinc-400">
          <p className="text-sm font-medium text-zinc-100">Scan this once, on the phone</p>
          {pairing?.links[0] && (
            <p className="mt-1 break-all font-mono text-[11px] text-zinc-500">
              {pairing.links[0].replace(/token=.*/, "token=…")}
            </p>
          )}
          <p className="mt-2">{pairing?.note}</p>
          <p className="mt-2 text-zinc-500">
            Both devices have to be on the same network, and this Mac has to be awake.
          </p>
          <div className="mt-3 flex flex-wrap gap-2">
            <button
              type="button"
              onClick={() => setShown(false)}
              className="rounded-md border border-zinc-700 px-3 py-1.5 text-xs text-zinc-300 hover:border-zinc-500"
            >
              Hide
            </button>
            <button
              type="button"
              onClick={rotate}
              className="rounded-md border border-rose-500/40 px-3 py-1.5 text-xs text-rose-300 hover:bg-rose-500/10"
            >
              Forget paired devices
            </button>
          </div>
          {note && <p className="mt-2 text-zinc-300">{note}</p>}
        </div>
      </div>
    </Panel>
  );
}
