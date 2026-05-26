"use client";

import { useEffect, useState } from "react";
import { Device, fetchDevices } from "@/lib/api";

function timeAgo(isoString: string | null): string {
  if (!isoString) return "never";
  const diff = Math.floor((Date.now() - new Date(isoString + "Z").getTime()) / 1000);
  if (diff < 60) return `${diff}s ago`;
  if (diff < 3600) return `${Math.floor(diff / 60)}m ago`;
  return `${Math.floor(diff / 3600)}h ago`;
}

export default function DeviceStatusBadge({ initial }: { initial: Device[] }) {
  const [devices, setDevices] = useState<Device[]>(initial);
  const [, tick] = useState(0);

  useEffect(() => {
    // refresh device list every 30s
    const dataId = setInterval(() => fetchDevices().then(setDevices), 30_000);
    // re-render timeAgo every 10s
    const tickId = setInterval(() => tick((n) => n + 1), 10_000);
    return () => {
      clearInterval(dataId);
      clearInterval(tickId);
    };
  }, []);

  const device = devices[0];
  if (!device) return null;

  return (
    <div className="flex items-center gap-2 shrink-0">
      <span className="relative flex h-2 w-2 shrink-0">
        {device.is_online && (
          <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-emerald-400 opacity-60" />
        )}
        <span
          className="relative inline-flex rounded-full h-2 w-2"
          style={{ background: device.is_online ? "#22c55e" : "#ef4444" }}
        />
      </span>
      <span className="hidden sm:inline text-xs font-mono text-muted-foreground whitespace-nowrap">
        {device.device_id}
      </span>
      <span className="hidden sm:inline text-xs text-muted-foreground/50">·</span>
      <span className="hidden sm:inline text-xs text-muted-foreground whitespace-nowrap">
        {device.is_online ? `online · ${timeAgo(device.last_seen_at)}` : `offline · ${timeAgo(device.last_seen_at)}`}
      </span>
    </div>
  );
}
