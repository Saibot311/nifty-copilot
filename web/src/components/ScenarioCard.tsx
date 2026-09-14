"use client";

import { useState } from "react";
import type { Scenario } from "@/lib/mock-data";

const KIND_STYLE: Record<Scenario["kind"], { label: string; ring: string; text: string }> = {
  bullish: { label: "Bullish Scenario", ring: "ring-emerald-500/30", text: "text-emerald-400" },
  bearish: { label: "Bearish Scenario", ring: "ring-rose-500/30", text: "text-rose-400" },
  no_trade: { label: "No-Trade View", ring: "ring-zinc-600/40", text: "text-zinc-400" },
};

export function ScenarioCard({ scenario }: { scenario: Scenario }) {
  const [whyOpen, setWhyOpen] = useState(false);
  const style = KIND_STYLE[scenario.kind];

  return (
    <div className={`flex flex-col gap-3 rounded-xl border border-zinc-800 bg-zinc-900/60 p-4 ring-1 ${style.ring}`}>
      <div className={`text-xs font-semibold uppercase tracking-wide ${style.text}`}>
        {style.label}
      </div>
      <h3 className="text-base font-medium text-zinc-100">{scenario.headline}</h3>

      {scenario.entryZone && (
        <dl className="grid grid-cols-2 gap-x-4 gap-y-1.5 text-sm">
          <Row label="Entry area" value={scenario.entryZone} />
          <Row label="Target" value={scenario.target} />
          <Row label="Stop-loss" value={scenario.stopLoss} />
          <Row label="Reward : risk" value={scenario.rewardRisk} />
        </dl>
      )}

      {scenario.confirmation.length > 0 && (
        <Section title="Needs to confirm">
          {scenario.confirmation}
        </Section>
      )}
      {scenario.invalidation.length > 0 && (
        <Section title="Invalidated by">
          {scenario.invalidation}
        </Section>
      )}

      {scenario.evidence && (
        <div className="rounded-lg bg-zinc-950/60 p-2.5 text-xs text-zinc-400">
          Historical sample: <span className="text-zinc-200">{scenario.evidence.sampleSize} occurrences</span> ·{" "}
          win rate <span className="text-zinc-200">{Math.round(scenario.evidence.winRate * 100)}%</span> ·{" "}
          median forward return <span className="text-zinc-200">{scenario.evidence.medianForwardReturn > 0 ? "+" : ""}{scenario.evidence.medianForwardReturn}%</span>
          <div className="mt-1 text-zinc-600">Placeholder numbers — not yet from a real backtest.</div>
        </div>
      )}

      <button
        onClick={() => setWhyOpen((v) => !v)}
        className="mt-1 self-start rounded-full border border-zinc-700 px-3 py-1 text-xs font-medium text-zinc-300 hover:bg-zinc-800"
      >
        {whyOpen ? "Hide reasoning" : "Why?"}
      </button>
      {whyOpen && (
        <ul className="space-y-1.5 rounded-lg bg-zinc-950/60 p-3 text-xs text-zinc-400">
          {scenario.why.map((line, i) => (
            <li key={i}>• {line}</li>
          ))}
        </ul>
      )}
    </div>
  );
}

function Row({ label, value }: { label: string; value?: string }) {
  return (
    <>
      <dt className="text-zinc-500">{label}</dt>
      <dd className="text-right font-mono text-zinc-200">{value}</dd>
    </>
  );
}

function Section({ title, children }: { title: string; children: string[] }) {
  return (
    <div className="text-xs">
      <div className="mb-1 font-medium text-zinc-500">{title}</div>
      <ul className="space-y-1 text-zinc-400">
        {children.map((line, i) => (
          <li key={i}>• {line}</li>
        ))}
      </ul>
    </div>
  );
}
