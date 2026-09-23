"use client";

import { useEffect, useState } from "react";
import { get } from "@/lib/api";

type Access = { local: boolean; token_required: boolean; paired: boolean };

/** Tells an unpaired phone what is wrong.
 *
 *  The page still renders — its data is fetched on the Mac — but everything
 *  live (the ticker, the journal, the paper book) is refused. Without this
 *  the phone shows a page that looks fine and quietly does nothing. */
export function PairingNotice() {
  const [access, setAccess] = useState<Access | null>(null);

  useEffect(() => {
    let alive = true;
    get<Access>("/api/access/check").then((r) => {
      if (alive && r.data) setAccess(r.data);
    });
    return () => { alive = false; };
  }, []);

  if (!access || access.local || access.paired) return null;

  return (
    <div className="border-b border-amber-500/30 bg-amber-500/[0.08] px-4 py-2 text-center text-xs text-amber-200 sm:px-8">
      This device isn&apos;t paired yet. On the Mac, open the dashboard and choose{" "}
      <span className="font-medium">Use this on my phone</span>, then scan the code. Until then the page
      cannot load anything live.
    </div>
  );
}
