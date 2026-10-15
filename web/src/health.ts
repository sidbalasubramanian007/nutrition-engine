import { useEffect, useState } from "react";
import { getHealth, type Health } from "./api.ts";

/** How long /api/health may take before we say the server is waking up. */
export const WAKING_AFTER_MS = 3000;

let pending: Promise<Health> | null = null;

/**
 * One /api/health request shared by everything that needs it on load (the planner's status line
 * and the waking-up notice). Not tied to a component, so React's dev double-mount can't cancel it.
 */
export function sharedHealth(): Promise<Health> {
  pending ??= getHealth();
  return pending;
}

/** True while the first health check has been pending for more than WAKING_AFTER_MS. */
export function useServerWaking(): boolean {
  const [waking, setWaking] = useState(false);
  useEffect(() => {
    let settled = false;
    const timer = window.setTimeout(() => {
      if (!settled) setWaking(true);
    }, WAKING_AFTER_MS);
    sharedHealth()
      .catch(() => undefined) // failures are reported by the planner's own status line
      .finally(() => {
        settled = true;
        window.clearTimeout(timer);
        setWaking(false);
      });
    return () => window.clearTimeout(timer);
  }, []);
  return waking;
}
