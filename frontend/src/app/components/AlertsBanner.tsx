"use client";

import { useEffect, useState } from "react";
import { AlertTriangle } from "lucide-react";
import { Alert, fetchAlerts } from "@/lib/api";

const ALERT_LABELS: Record<string, string> = {
  soil_moisture_low: "Soil moisture critical",
  high_temperature:  "Temperature spike",
  low_humidity:      "Humidity too low",
};

export default function AlertsBanner({ initial }: { initial: Alert[] }) {
  const [alerts, setAlerts] = useState<Alert[]>(initial);

  useEffect(() => {
    const id = setInterval(() => fetchAlerts().then(setAlerts), 30_000);
    return () => clearInterval(id);
  }, []);

  if (alerts.length === 0) return null;

  return (
    <div className="rounded-lg border border-red-800/60 bg-red-950/30 px-4 py-3">
      <div className="flex flex-col gap-2">
        {alerts.map((a) => (
          <div key={`${a.device_id}-${a.alert_type}`} className="flex items-center gap-2.5">
            <AlertTriangle className="h-3.5 w-3.5 shrink-0 text-red-400" />
            <span className="text-sm font-medium text-red-200">
              {ALERT_LABELS[a.alert_type] ?? a.alert_type}
            </span>
            <span className="text-xs text-red-400/70">— {a.device_id}</span>
          </div>
        ))}
      </div>
    </div>
  );
}
