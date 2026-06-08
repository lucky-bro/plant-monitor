function apiBase(): string {
  if (typeof window === "undefined") {
    return process.env.BACKEND_URL ?? "http://localhost:8000";
  }
  return process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";
}

export interface Telemetry {
  device_id: string;
  message_id: string;
  temperature: number | null;
  humidity: number | null;
  soil_moisture: number | null;
  light: number | null;
  timestamp: number;
}

export interface Device {
  device_id: string;
  is_online: boolean;
  last_seen_at: string | null;
}

export interface Alert {
  device_id: string;
  alert_type: string;
  last_sent_at: string | null;
  updated_at: string | null;
}

export interface HistoryPoint {
  timestamp: number;
  temperature: number | null;
  humidity: number | null;
  soil_moisture: number | null;
  light: number | null;
}

export async function fetchLatestTelemetry(): Promise<Telemetry | null> {
  try {
    const res = await fetch(`${apiBase()}/telemetry`, { cache: "no-store" });
    if (!res.ok) return null;
    const json = await res.json();
    return json.data?.[0] ?? null;
  } catch {
    return null;
  }
}

export async function fetchDevices(): Promise<Device[]> {
  try {
    const res = await fetch(`${apiBase()}/devices`, { cache: "no-store" });
    if (!res.ok) return [];
    const json = await res.json();
    return json.devices ?? [];
  } catch {
    return [];
  }
}

export async function fetchAlerts(): Promise<Alert[]> {
  try {
    const res = await fetch(`${apiBase()}/alerts`, { cache: "no-store" });
    if (!res.ok) return [];
    const json = await res.json();
    return json.alerts ?? [];
  } catch {
    return [];
  }
}

export async function fetchHistory(
  deviceId: string,
  range: "24h" | "7d"
): Promise<HistoryPoint[]> {
  try {
    const res = await fetch(
      `${apiBase()}/device/${deviceId}/history?range=${range}`,
      { cache: "no-store" }
    );
    if (!res.ok) return [];
    const json = await res.json();
    return json.data ?? [];
  } catch {
    return [];
  }
}

export interface Insight {
  id:           number;
  text:         string;
  trigger:      string;
  generated_at: string | null;
  period_start: string | null;
  period_end:   string | null;
}

export async function fetchInsight(deviceId = "plant-01"): Promise<Insight | null> {
  try {
    const res = await fetch(`${apiBase()}/insights?device_id=${deviceId}`, { cache: "no-store" });
    if (!res.ok) return null;
    const json = await res.json();
    return json.insight ?? null;
  } catch {
    return null;
  }
}

export function getEventsUrl(): string {
  return `${process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000"}/events`;
}
