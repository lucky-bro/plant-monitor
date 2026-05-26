"use client";

import { useEffect, useState } from "react";
import { Thermometer, Droplets, Leaf, Sun } from "lucide-react";
import { Telemetry, getEventsUrl } from "@/lib/api";

type Status = "ok" | "warn" | "critical";

function getStatus(field: keyof Telemetry, value: number | null): Status {
  if (value === null || value < 0) return "ok";
  if (field === "soil_moisture") {
    if (value < 25) return "critical";
    if (value < 40) return "warn";
  }
  if (field === "temperature") {
    if (value > 32) return "critical";
    if (value > 28) return "warn";
  }
  if (field === "humidity") {
    if (value < 40) return "critical";
    if (value < 45) return "warn";
  }
  return "ok";
}

const STATUS_BORDER: Record<Status, string> = {
  ok:       "#22c55e",
  warn:     "#eab308",
  critical: "#ef4444",
};
const STATUS_ICON: Record<Status, string> = {
  ok:       "text-emerald-400",
  warn:     "text-yellow-400",
  critical: "text-red-400",
};
const STATUS_VALUE: Record<Status, string> = {
  ok:       "text-emerald-400",
  warn:     "text-yellow-400",
  critical: "text-red-400",
};

interface MetricProps {
  label: string;
  value: string;
  unit: string;
  status: Status;
  icon: React.ReactNode;
}

function MetricCard({ label, value, unit, status, icon }: MetricProps) {
  return (
    <div
      className="rounded-lg bg-card flex flex-col gap-3 px-5 py-4 border border-border/50"
      style={{ borderTop: `3px solid ${STATUS_BORDER[status]}` }}
    >
      <div className={`flex items-center gap-1.5 ${STATUS_ICON[status]}`}>
        {icon}
        <span className="text-[11px] font-semibold uppercase tracking-widest text-muted-foreground">
          {label}
        </span>
      </div>
      <div className="flex items-end gap-1.5">
        <span className={`text-5xl font-bold tabular-nums leading-none ${STATUS_VALUE[status]}`}>
          {value}
        </span>
        {unit && (
          <span className="text-xl text-muted-foreground mb-0.5">{unit}</span>
        )}
      </div>
    </div>
  );
}

function toMetrics(t: Telemetry | null): MetricProps[] {
  return [
    {
      label:  "Temperature",
      value:  t?.temperature != null ? t.temperature.toFixed(1) : "—",
      unit:   "°C",
      status: getStatus("temperature", t?.temperature ?? null),
      icon:   <Thermometer className="h-3.5 w-3.5" />,
    },
    {
      label:  "Humidity",
      value:  t?.humidity != null ? t.humidity.toFixed(1) : "—",
      unit:   "%",
      status: getStatus("humidity", t?.humidity ?? null),
      icon:   <Droplets className="h-3.5 w-3.5" />,
    },
    {
      label:  "Soil Moisture",
      value:  t?.soil_moisture != null ? String(t.soil_moisture) : "—",
      unit:   "%",
      status: getStatus("soil_moisture", t?.soil_moisture ?? null),
      icon:   <Leaf className="h-3.5 w-3.5" />,
    },
    {
      label:  "Light",
      value:  t?.light != null && t.light >= 0 ? String(t.light) : "n/a",
      unit:   t?.light != null && t.light >= 0 ? "lux" : "",
      status: "ok",
      icon:   <Sun className="h-3.5 w-3.5" />,
    },
  ];
}

function LiveIndicator({ time }: { time: Date }) {
  return (
    <div className="flex items-center gap-2">
      <span className="relative flex h-2 w-2">
        <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-emerald-400 opacity-60" />
        <span className="relative inline-flex rounded-full h-2 w-2 bg-emerald-500" />
      </span>
      <span className="text-xs font-mono text-muted-foreground">
        {time.toLocaleTimeString()}
      </span>
    </div>
  );
}

export default function HeroMetrics({ initial }: { initial: Telemetry | null }) {
  const [telemetry, setTelemetry] = useState<Telemetry | null>(initial);
  const [lastUpdate, setLastUpdate] = useState<Date | null>(initial ? new Date() : null);

  useEffect(() => {
    const es = new EventSource(getEventsUrl());
    es.onmessage = (e) => {
      try {
        setTelemetry(JSON.parse(e.data) as Telemetry);
        setLastUpdate(new Date());
      } catch {}
    };
    return () => es.close();
  }, []);

  return (
    <div>
      <div className="flex items-center justify-between mb-3">
        <span className="text-[11px] font-semibold uppercase tracking-widest text-muted-foreground">
          Current readings
        </span>
        {lastUpdate && <LiveIndicator time={lastUpdate} />}
      </div>
      <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
        {toMetrics(telemetry).map((m) => (
          <MetricCard key={m.label} {...m} />
        ))}
      </div>
    </div>
  );
}
