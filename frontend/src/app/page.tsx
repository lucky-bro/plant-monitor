import { Leaf } from "lucide-react";
import { fetchLatestTelemetry, fetchDevices, fetchAlerts } from "@/lib/api";
import HeroMetrics from "./components/HeroMetrics";
import AlertsBanner from "./components/AlertsBanner";
import HistoryCharts from "./components/HistoryCharts";
import DeviceStatusBadge from "./components/DeviceStatusBadge";

export default async function Page() {
  const [telemetry, devices, alerts] = await Promise.all([
    fetchLatestTelemetry(),
    fetchDevices(),
    fetchAlerts(),
  ]);

  const primaryDevice = devices[0]?.device_id ?? "plant-01";

  return (
    <main className="min-h-screen px-4 py-8 max-w-5xl mx-auto flex flex-col gap-5">
      <header className="flex items-center justify-between pb-2 border-b border-border/30">
        <div className="flex items-center gap-3 min-w-0">
          <Leaf className="h-4 w-4 text-emerald-500 shrink-0" />
          <span className="text-base font-bold tracking-tight whitespace-nowrap">plant-monitor</span>
          <span className="text-[10px] font-mono text-muted-foreground border border-border/50 rounded px-1.5 py-0.5 shrink-0">
            v1
          </span>
        </div>
        <DeviceStatusBadge initial={devices} />
      </header>

      <AlertsBanner initial={alerts} />

      <div className="flex flex-col gap-5">
        <HeroMetrics initial={telemetry} />
        <HistoryCharts deviceId={primaryDevice} />
      </div>
    </main>
  );
}
