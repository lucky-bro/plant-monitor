"use client";

import { useEffect, useState } from "react";
import {
  AreaChart, Area, XAxis, YAxis, Tooltip,
  ResponsiveContainer, CartesianGrid,
} from "recharts";
import { HistoryPoint, fetchHistory } from "@/lib/api";

type Range = "24h" | "7d";

function formatTs(ts: number, range: Range): string {
  const d = new Date(ts * 1000);
  if (range === "24h") return d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
  return d.toLocaleDateString([], { month: "short", day: "numeric" });
}

const CHARTS: { key: keyof HistoryPoint; label: string; unit: string; color: string; gradientId: string }[] = [
  { key: "temperature",  label: "Temperature",  unit: "°C", color: "#f97316", gradientId: "gradTemp"  },
  { key: "humidity",     label: "Humidity",     unit: "%",  color: "#3b82f6", gradientId: "gradHum"   },
  { key: "soil_moisture",label: "Soil Moisture",unit: "%",  color: "#22c55e", gradientId: "gradSoil"  },
];

function Chart({
  data, chartKey, label, unit, color, gradientId, range,
}: {
  data: HistoryPoint[];
  chartKey: keyof HistoryPoint;
  label: string;
  unit: string;
  color: string;
  gradientId: string;
  range: Range;
}) {
  return (
    <div className="rounded-lg bg-card border border-border/50 px-5 pt-4 pb-3">
      <p className="text-[11px] font-semibold uppercase tracking-widest text-muted-foreground mb-4">
        {label} <span className="normal-case font-normal">({unit})</span>
      </p>
      <ResponsiveContainer width="100%" height={130}>
        <AreaChart data={data} margin={{ top: 4, right: 4, bottom: 0, left: -24 }}>
          <defs>
            <linearGradient id={gradientId} x1="0" y1="0" x2="0" y2="1">
              <stop offset="5%"  stopColor={color} stopOpacity={0.25} />
              <stop offset="95%" stopColor={color} stopOpacity={0}    />
            </linearGradient>
          </defs>
          <CartesianGrid strokeDasharray="3 3" stroke="oklch(1 0 0 / 6%)" vertical={false} />
          <XAxis
            dataKey="timestamp"
            tickFormatter={(v) => formatTs(v, range)}
            tick={{ fontSize: 10, fill: "oklch(0.556 0 0)" }}
            axisLine={false}
            tickLine={false}
            interval="preserveStartEnd"
          />
          <YAxis
            tick={{ fontSize: 10, fill: "oklch(0.556 0 0)" }}
            axisLine={false}
            tickLine={false}
            domain={["auto", "auto"]}
          />
          <Tooltip
            contentStyle={{
              background: "oklch(0.16 0.005 250 / 95%)",
              border: "1px solid oklch(1 0 0 / 10%)",
              borderRadius: 8,
              fontSize: 12,
              color: "oklch(0.985 0 0)",
              backdropFilter: "blur(8px)",
            }}
            labelFormatter={(v) => formatTs(v as number, range)}
            formatter={(v) => [`${v}${unit}`, label]}
            cursor={{ stroke: color, strokeWidth: 1, strokeOpacity: 0.4 }}
          />
          <Area
            type="monotone"
            dataKey={chartKey as string}
            stroke={color}
            strokeWidth={2}
            fill={`url(#${gradientId})`}
            dot={false}
            connectNulls
          />
        </AreaChart>
      </ResponsiveContainer>
    </div>
  );
}

export default function HistoryCharts({ deviceId }: { deviceId: string }) {
  const [range, setRange]     = useState<Range>("24h");
  const [data, setData]       = useState<HistoryPoint[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    setLoading(true);
    fetchHistory(deviceId, range).then((d) => {
      setData(d);
      setLoading(false);
    });
  }, [deviceId, range]);

  return (
    <div className="flex flex-col gap-3">
      <div className="flex items-center justify-between">
        <span className="text-[11px] font-semibold uppercase tracking-widest text-muted-foreground">
          History
        </span>
        <div className="flex gap-1 rounded-md border border-border/50 p-0.5 bg-card">
          {(["24h", "7d"] as Range[]).map((r) => (
            <button
              key={r}
              onClick={() => setRange(r)}
              className={`px-3 py-1 rounded text-xs font-semibold transition-colors ${
                range === r
                  ? "bg-primary text-primary-foreground"
                  : "text-muted-foreground hover:text-foreground"
              }`}
            >
              {r}
            </button>
          ))}
        </div>
      </div>

      {loading ? (
        <p className="text-sm text-muted-foreground py-4">Loading...</p>
      ) : data.length === 0 ? (
        <p className="text-sm text-muted-foreground py-4">No data for this range.</p>
      ) : (
        <div className="flex flex-col gap-3">
          {CHARTS.map((c) => (
            <Chart key={c.key} data={data} chartKey={c.key} label={c.label} unit={c.unit} color={c.color} gradientId={c.gradientId} range={range} />
          ))}
        </div>
      )}
    </div>
  );
}
