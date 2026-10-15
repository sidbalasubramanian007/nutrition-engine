import { useCallback, useEffect, useRef, useState } from "react";
import {
  ApiError,
  getHealth,
  optimizePlan,
  savePlan,
  type DailyMeal,
  type DailyTargets,
  type LockedItem,
  type Plan,
} from "./api.ts";

/** Time budget the app gives the solver (seconds). */
export const PLAN_TIME_LIMIT = 1;

export type SaveState = { kind: "idle" } | { kind: "saving" } | { kind: "saved"; id: number } | { kind: "error"; message: string };

interface LastRequest {
  targets: DailyTargets;
  onlyVerified: boolean;
}

/** Friendly text for a failed request; also reports whether the server was unreachable. */
export function describeError(error: unknown): { message: string; unreachable: boolean } {
  if (error instanceof ApiError) {
    if (error.status === 0) return { message: "The planner can't reach the server.", unreachable: true };
    if (error.status === 503) return { message: "The server can't reach its database.", unreachable: false };
    if (error.status === 422) return { message: `The server rejected that request: ${error.message}`, unreachable: false };
    return { message: error.message, unreachable: false };
  }
  return { message: "Something went wrong. Please try again.", unreachable: false };
}

export function usePlanner() {
  const [plan, setPlan] = useState<Plan | null>(null);
  /** Targets the current plan was made for (the scoreboard compares against these). */
  const [planTargets, setPlanTargets] = useState<DailyTargets | null>(null);
  const [infeasibleReason, setInfeasibleReason] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [unreachable, setUnreachable] = useState(false);
  const [dbDown, setDbDown] = useState(false);
  const [locked, setLocked] = useState<LockedItem[]>([]);
  const [excluded, setExcluded] = useState<string[]>([]);
  const [saveState, setSaveState] = useState<SaveState>({ kind: "idle" });

  const lastRequest = useRef<LastRequest | null>(null);
  const inFlight = useRef<AbortController | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    getHealth(controller.signal)
      .then((health) => {
        setUnreachable(false);
        setDbDown(!health.db);
      })
      .catch((e: unknown) => {
        if (e instanceof DOMException && e.name === "AbortError") return;
        setUnreachable(describeError(e).unreachable);
      });
    return () => controller.abort();
  }, []);

  const run = useCallback(
    async (targets: DailyTargets, onlyVerified: boolean, nextLocked: LockedItem[], nextExcluded: string[]) => {
      inFlight.current?.abort(); // a newer request always wins
      const controller = new AbortController();
      inFlight.current = controller;
      lastRequest.current = { targets, onlyVerified };
      setLoading(true);
      setError(null);
      try {
        const result = await optimizePlan(
          {
            targets,
            exclude_estimated: onlyVerified,
            time_limit: PLAN_TIME_LIMIT,
            locked: nextLocked,
            excluded: nextExcluded,
          },
          controller.signal,
        );
        setUnreachable(false);
        setDbDown(false);
        if (result.status === "infeasible") {
          // Keep the last plan on screen so locks can still be changed
          setInfeasibleReason(result.message ?? "No plan fits these settings.");
        } else {
          setPlan(result);
          setPlanTargets(targets);
          setInfeasibleReason(null);
          setSaveState({ kind: "idle" });
        }
      } catch (e) {
        if (e instanceof DOMException && e.name === "AbortError") return;
        const { message, unreachable: down } = describeError(e);
        setUnreachable(down);
        if (e instanceof ApiError && e.status === 503) setDbDown(true);
        setError(message);
      } finally {
        if (inFlight.current === controller) {
          inFlight.current = null;
          setLoading(false);
        }
      }
    },
    [],
  );

  /** Plans (or re-plans) for these targets, keeping the current locks and exclusions. */
  const planDay = useCallback(
    (targets: DailyTargets, onlyVerified: boolean) => run(targets, onlyVerified, locked, excluded),
    [run, locked, excluded],
  );

  const isLocked = useCallback(
    (name: string, meal: string, servings: number) =>
      locked.some((l) => l.name === name && l.meal === meal && l.servings === servings),
    [locked],
  );

  const toggleLock = useCallback((name: string, meal: DailyMeal, servings: number) => {
    setLocked((current) =>
      current.some((l) => l.name === name && l.meal === meal)
        ? current.filter((l) => !(l.name === name && l.meal === meal))
        : [...current, { name, meal, servings }],
    );
  }, []);

  /** Excludes a food (dropping any lock on it) and re-plans straight away. */
  const removeFood = useCallback(
    (name: string) => {
      const nextExcluded = excluded.includes(name) ? excluded : [...excluded, name];
      const nextLocked = locked.filter((l) => l.name !== name);
      setExcluded(nextExcluded);
      setLocked(nextLocked);
      if (lastRequest.current) {
        void run(lastRequest.current.targets, lastRequest.current.onlyVerified, nextLocked, nextExcluded);
      }
    },
    [excluded, locked, run],
  );

  const clearConstraints = useCallback(() => {
    setLocked([]);
    setExcluded([]);
  }, []);

  const save = useCallback(async () => {
    if (!plan || !planTargets) return;
    setSaveState({ kind: "saving" });
    try {
      const { id } = await savePlan({ plan, targets: planTargets });
      setSaveState({ kind: "saved", id });
    } catch (e) {
      const { message, unreachable: down } = describeError(e);
      if (down) setUnreachable(true);
      setSaveState({ kind: "error", message });
    }
  }, [plan, planTargets]);

  return {
    plan,
    planTargets,
    infeasibleReason,
    loading,
    error,
    setError,
    unreachable,
    dbDown,
    locked,
    excluded,
    saveState,
    planDay,
    isLocked,
    toggleLock,
    removeFood,
    clearConstraints,
    save,
  };
}

export type Planner = ReturnType<typeof usePlanner>;
