"use client";

import { useEffect, useState } from "react";
import { Sparkles } from "lucide-react";
import { Insight, fetchInsight } from "@/lib/api";

const STALE_HOURS = 12;

function timeAgo(isoString: string): string {
  const diff = Math.floor((Date.now() - new Date(isoString + "Z").getTime()) / 1000);
  if (diff < 60) return `${diff}s ago`;
  if (diff < 3600) return `${Math.floor(diff / 60)}m ago`;
  if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`;
  return `${Math.floor(diff / 86400)}d ago`;
}

function hoursOld(isoString: string): number {
  return (Date.now() - new Date(isoString + "Z").getTime()) / 3_600_000;
}

export default function AIInsight({ initial }: { initial: Insight | null }) {
  const [insight, setInsight] = useState<Insight | null>(initial);

  useEffect(() => {
    // Refresh every 5 min so newly generated insights show up without page reload
    const id = setInterval(() => fetchInsight().then(setInsight), 5 * 60 * 1000);
    return () => clearInterval(id);
  }, []);

  const isStale = insight?.generated_at && hoursOld(insight.generated_at) > STALE_HOURS;

  return (
    <div className="rounded-lg bg-card border border-border/50 px-5 py-4">
      <div className="flex items-center justify-between mb-3">
        <div className="flex items-center gap-2">
          <Sparkles className="h-3.5 w-3.5 text-purple-400" />
          <span className="text-[11px] font-semibold uppercase tracking-widest text-muted-foreground">
            AI Insight
          </span>
        </div>
        {insight?.generated_at && (
          <div className="flex items-center gap-2">
            {isStale && (
              <span className="text-[10px] uppercase tracking-wider text-yellow-400 border border-yellow-400/40 rounded px-1.5 py-0.5">
                stale
              </span>
            )}
            <span className="text-xs text-muted-foreground font-mono">
              {timeAgo(insight.generated_at)}
            </span>
          </div>
        )}
      </div>

      {insight ? (
        <p className="text-sm leading-relaxed text-foreground/90">{insight.text}</p>
      ) : (
        <p className="text-sm text-muted-foreground italic">
          No insight yet — first one will appear shortly after enough data is collected.
        </p>
      )}
    </div>
  );
}
