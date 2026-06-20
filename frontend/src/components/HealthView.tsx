import { useCallback, useEffect, useState } from "react";

import { fetchHealth, type ReadinessReport } from "../api/health";

type State =
  | { kind: "loading" }
  | { kind: "loaded"; report: ReadinessReport }
  | { kind: "unavailable" };

export function HealthView() {
  const [state, setState] = useState<State>({ kind: "loading" });

  const refresh = useCallback(async () => {
    try {
      const report = await fetchHealth();
      setState({ kind: "loaded", report });
    } catch {
      setState({ kind: "unavailable" });
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  if (state.kind === "loading") {
    return (
      <main>
        <h1>System Liveness</h1>
        <p role="status" data-status="loading">
          Loading…
        </p>
      </main>
    );
  }

  if (state.kind === "unavailable") {
    return (
      <main>
        <h1>System Liveness</h1>
        <p role="status" data-status="unavailable">
          Status: unavailable / unknown
        </p>
        <button onClick={() => void refresh()}>Retry</button>
      </main>
    );
  }

  const { report } = state;
  return (
    <main>
      <h1>System Liveness</h1>
      <p role="status" data-status={report.status}>
        Overall: {report.status}
      </p>
      <ul>
        {report.checks.map((check) => (
          <li key={check.name} data-passed={check.passed}>
            {check.name}: {check.passed ? "pass" : "fail"}
            {check.detail ? ` (${check.detail})` : ""}
          </li>
        ))}
      </ul>
      <button onClick={() => void refresh()}>Refresh</button>
    </main>
  );
}
