import type { ZerodhaStatus } from "@/lib/api";
import { zerodhaLoginUrl } from "@/lib/api";

function time(iso?: string | null) {
  if (!iso) return null;
  return new Date(iso).toLocaleTimeString("en-IN", { hour: "2-digit", minute: "2-digit", timeZone: "Asia/Kolkata" });
}

/** Header pill: is there a Kite session today, and the run of days that had
 *  one. Without it, 15-minute bars and live tracking are the parts missing. */
export function SessionStatus({ status }: { status: ZerodhaStatus | null }) {
  if (!status) return null;
  const h = status.history;

  if (status.logged_in) {
    return (
      <span
        className="flex items-center gap-1.5 text-[11px] text-zinc-500"
        title={`Zerodha session since ${time(status.issued_at)} IST. ${h.current_streak} day streak · ${h.days_without_a_session} day(s) without a session on record.`}
      >
        <span className="h-1.5 w-1.5 rounded-full bg-emerald-400" />
        Zerodha {time(status.issued_at)}
        {h.current_streak > 1 && <span className="text-zinc-600">· {h.current_streak}d</span>}
      </span>
    );
  }

  return (
    <a
      href={zerodhaLoginUrl()}
      className="flex items-center gap-1.5 rounded-full border border-amber-500/40 bg-amber-500/10 px-2.5 py-0.5 text-[11px] font-medium text-amber-300 hover:bg-amber-500/20 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-amber-400/60"
      title={status.reason ?? "No Kite session today — 15-minute bars and live tracking are skipped until you log in."}
    >
      <span className="h-1.5 w-1.5 rounded-full bg-amber-400" />
      Log in to Zerodha
    </a>
  );
}
