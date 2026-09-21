"use client";

import { useState } from "react";

import { type CopilotAnswer, type CopilotStatus, copilotRequest } from "@/lib/api";
import { Panel } from "./ui";

function Answer({ a }: { a: CopilotAnswer }) {
  if (!a.ok) {
    return <p className="text-xs leading-relaxed text-amber-300/90">{a.reason}</p>;
  }
  return (
    <div>
      <div className="whitespace-pre-line text-sm leading-relaxed text-zinc-200">{a.answer}</div>
      <p className="mt-2 text-[10px] text-zinc-600">
        {a.model ? `${a.provider} · ${a.model} · ` : ""}every number checked against the computed data ·{" "}
        {a.review?.checked
          ? `Jev checked ${a.review.claims_checked ?? 0} sentence${a.review.claims_checked === 1 ? "" : "s"} against it, and found no forecast`
          : "Jev checks skipped"}
        {a.cached ? " · saved explanation" : ""}
      </p>
    </div>
  );
}

export function CopilotCard({ status }: { status: CopilotStatus | null }) {
  const [explain, setExplain] = useState<CopilotAnswer | null>(null);
  const [answer, setAnswer] = useState<CopilotAnswer | null>(null);
  const [question, setQuestion] = useState("");
  const [busy, setBusy] = useState<"explain" | "ask" | null>(null);
  const [error, setError] = useState<string | null>(null);

  if (!status) return null;
  if (!status.configured) {
    return (
      <Panel className="p-4 text-xs leading-relaxed text-zinc-500">
        Copilot is off: no API key yet. Add <code className="text-zinc-400">LLM_PROVIDER</code> and{" "}
        <code className="text-zinc-400">LLM_API_KEY</code> to <code className="text-zinc-400">api/.env</code>.
      </Panel>
    );
  }

  async function run(kind: "explain" | "ask") {
    setBusy(kind);
    setError(null);
    const res = kind === "explain" ? await copilotRequest("/api/copilot/explain") : await copilotRequest("/api/copilot/ask", question);
    if (res.error) setError(res.error);
    else if (kind === "explain") setExplain(res.data!);
    else setAnswer(res.data!);
    setBusy(null);
  }

  return (
    <Panel className="p-4">
      {explain ? (
        <Answer a={explain} />
      ) : (
        <button
          onClick={() => run("explain")}
          disabled={busy !== null}
          className="rounded-lg border border-indigo-500/40 bg-indigo-500/10 px-3 py-1.5 text-xs font-medium text-indigo-200 hover:bg-indigo-500/20 disabled:opacity-50"
        >
          {busy === "explain" ? "Explaining…" : "Explain today in plain language"}
        </button>
      )}

      <form
        className="mt-4 flex gap-2"
        onSubmit={(e) => {
          e.preventDefault();
          if (question.trim()) run("ask");
        }}
      >
        <input
          value={question}
          onChange={(e) => setQuestion(e.target.value)}
          placeholder="Ask about today's dashboard…"
          maxLength={1000}
          className="min-w-0 flex-1 rounded-lg border border-zinc-800 bg-zinc-950/60 px-3 py-1.5 text-sm text-zinc-200 placeholder:text-zinc-600 focus:border-indigo-500/50 focus:outline-none"
        />
        <button
          type="submit"
          disabled={busy !== null || !question.trim()}
          className="shrink-0 rounded-lg border border-zinc-700 px-3 py-1.5 text-xs text-zinc-300 hover:bg-zinc-800 disabled:opacity-50"
        >
          {busy === "ask" ? "…" : "Ask"}
        </button>
      </form>
      {answer && (
        <div className="mt-3">
          <Answer a={answer} />
        </div>
      )}
      {error && <p className="mt-3 text-xs text-rose-400">{error}</p>}
      <p className="mt-3 text-[10px] leading-relaxed text-zinc-600">
        Explains what the system computed; it can&apos;t predict or add numbers — answers with any number not in the data
        are withheld{status.guards.forecast ? ", as are answers that forecast the market, tell you to trade, or say something the computed data doesn't back" : ""}.
        Uses the {status.provider} free tier: your questions and today&apos;s market figures are sent to it and may be
        used to improve its models.
      </p>
    </Panel>
  );
}
