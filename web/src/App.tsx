import { useCallback, useEffect, useState } from "react";
import { API_URL, ApiError, getHealth, type Health } from "./api.ts";
import "./App.css";

type HealthState =
  | { kind: "checking" }
  | { kind: "ok"; health: Health }
  | { kind: "unreachable"; message: string };

function StatusRow({ label, ok, detail }: { label: string; ok: boolean | null; detail: string }) {
  const state = ok === null ? "unknown" : ok ? "ok" : "down";
  return (
    <div className="status-row">
      <span className={`status-dot status-dot--${state}`} aria-hidden="true" />
      <span className="status-label">{label}</span>
      <span className="status-detail">{detail}</span>
    </div>
  );
}

export default function App() {
  const [state, setState] = useState<HealthState>({ kind: "checking" });

  const check = useCallback((signal?: AbortSignal) => {
    setState({ kind: "checking" });
    getHealth(signal)
      .then((health) => setState({ kind: "ok", health }))
      .catch((error: unknown) => {
        if (error instanceof DOMException && error.name === "AbortError") return;
        const message = error instanceof ApiError ? error.message : "Unexpected error";
        setState({ kind: "unreachable", message });
      });
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    check(controller.signal);
    return () => controller.abort();
  }, [check]);

  const backendOk = state.kind === "checking" ? null : state.kind === "ok";
  const dbOk = state.kind === "ok" ? state.health.db : null;

  return (
    <main className="app">
      <header className="app-header">
        <h1 className="number app-title">Nutrition engine</h1>
        <p className="muted">Meal plans that hit your calorie, protein, carb and fat targets.</p>
      </header>

      <section className="panel" aria-labelledby="status-heading">
        <h2 id="status-heading" className="panel-title">
          Connection status
        </h2>
        <div role="status" aria-live="polite" className="status-list">
          <StatusRow
            label="Backend"
            ok={backendOk}
            detail={
              state.kind === "checking"
                ? "Checking…"
                : state.kind === "ok"
                  ? "Reachable"
                  : `Not reachable. ${state.message}`
            }
          />
          <StatusRow
            label="Database"
            ok={dbOk}
            detail={
              state.kind === "checking"
                ? "Checking…"
                : state.kind === "ok"
                  ? state.health.db
                    ? "Reachable"
                    : "Not reachable from the backend"
                  : "Unknown until the backend is reachable"
            }
          />
        </div>
        <div className="status-footer">
          <p className="muted">API: {API_URL}</p>
          <button type="button" onClick={() => check()} disabled={state.kind === "checking"}>
            Check again
          </button>
        </div>
      </section>
    </main>
  );
}
