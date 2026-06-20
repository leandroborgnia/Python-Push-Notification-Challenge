export type SubsystemCheck = {
  name: string;
  passed: boolean;
  detail: string | null;
};

export type ReadinessReport = {
  status: string;
  checked_at: string;
  checks: SubsystemCheck[];
};

const BASE: string = import.meta.env.VITE_API_BASE_URL ?? "";

export async function fetchHealth(): Promise<ReadinessReport> {
  const res = await fetch(`${BASE}/health`);
  // /health returns 200 (healthy) or 503 (not-healthy); both carry the report body.
  if (res.status !== 200 && res.status !== 503) {
    throw new Error(`unexpected status ${res.status}`);
  }
  return (await res.json()) as ReadinessReport;
}
