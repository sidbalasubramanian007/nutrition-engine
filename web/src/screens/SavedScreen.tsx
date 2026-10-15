import { useEffect, useRef, useState } from "react";
import { deletePlan, getPlan, listPlans, type Macros, type SavedPlan, type SavedPlanSummary, type Targets } from "../api.ts";
import Timeline from "../components/Timeline.tsx";
import { formatNumber } from "../format.ts";
import { describeError } from "../usePlanner.ts";
import "./SavedScreen.css";

const NUMBERS = [
  { key: "calories", unit: "kcal", word: "" },
  { key: "protein", unit: "g", word: "protein" },
  { key: "carbs", unit: "g", word: "carbs" },
  { key: "fat", unit: "g", word: "fat" },
] as const;

// Same weights as the solver's penalty, so "largest miss" means what the penalty means
const WEIGHTS = { calories: 20, protein: 100, carbs: 20, fat: 20 } as const;
const UNITS = { calories: "kcal", protein: "g", carbs: "g", fat: "g" } as const;

const dateFormat = new Intl.DateTimeFormat("en-US", { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" });

/** "Oct 15, 9:42 pm" */
function formatDate(iso: string): string {
  return dateFormat.format(new Date(iso)).replace(/\s?([AP])M$/, (_, x: string) => ` ${x.toLowerCase()}m`);
}

/** "on target" if every macro is within 1%, otherwise the largest (penalty-weighted) miss, e.g. "fat 6 g under". */
function missInWords(macros: Macros, targets: Targets): string {
  let worst: { key: keyof typeof WEIGHTS; diff: number; weighted: number } | null = null;
  for (const key of Object.keys(WEIGHTS) as (keyof typeof WEIGHTS)[]) {
    const diff = macros[key] - targets[key];
    if (Math.abs(diff) <= Math.abs(targets[key]) * 0.01) continue;
    const weighted = Math.abs(diff) * WEIGHTS[key];
    if (!worst || weighted > worst.weighted) worst = { key, diff, weighted };
  }
  if (!worst) return "on target";
  return `${worst.key} ${formatNumber(Math.abs(worst.diff))} ${UNITS[worst.key]} ${worst.diff > 0 ? "over" : "under"}`;
}

type Detail = { kind: "loading" } | { kind: "ok"; plan: SavedPlan } | { kind: "error"; message: string };

export default function SavedScreen({ active }: { active: boolean }) {
  const [plans, setPlans] = useState<SavedPlanSummary[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [expanded, setExpanded] = useState<number | null>(null);
  const [details, setDetails] = useState<Record<number, Detail>>({});
  const [confirming, setConfirming] = useState<number | null>(null);
  const [deleting, setDeleting] = useState(false);
  const [deleteError, setDeleteError] = useState<string | null>(null);
  const headingRef = useRef<HTMLHeadingElement>(null);
  const keepRef = useRef<HTMLButtonElement>(null);
  const deleteRef = useRef<HTMLButtonElement>(null);

  // Refresh whenever the screen is shown, so newly saved plans appear
  useEffect(() => {
    if (!active) return;
    const controller = new AbortController();
    setError(null);
    listPlans(20, controller.signal)
      .then(setPlans)
      .catch((e: unknown) => {
        if (e instanceof DOMException && e.name === "AbortError") return;
        setError(describeError(e).message);
      });
    return () => controller.abort();
  }, [active]);

  useEffect(() => {
    if (confirming !== null) keepRef.current?.focus();
  }, [confirming]);

  function toggle(id: number) {
    setConfirming(null);
    setDeleteError(null);
    if (expanded === id) {
      setExpanded(null);
      return;
    }
    setExpanded(id);
    if (!details[id] || details[id].kind === "error") {
      setDetails((d) => ({ ...d, [id]: { kind: "loading" } }));
      getPlan(id)
        .then((plan) => setDetails((d) => ({ ...d, [id]: { kind: "ok", plan } })))
        .catch((e: unknown) => setDetails((d) => ({ ...d, [id]: { kind: "error", message: describeError(e).message } })));
    }
  }

  async function confirmDelete(id: number) {
    setDeleting(true);
    setDeleteError(null);
    try {
      await deletePlan(id);
      setPlans((list) => (list ?? []).filter((p) => p.id !== id));
      setExpanded(null);
      setConfirming(null);
      headingRef.current?.focus();
    } catch (e) {
      setDeleteError(describeError(e).message);
    } finally {
      setDeleting(false);
    }
  }

  function keep() {
    setConfirming(null);
    requestAnimationFrame(() => deleteRef.current?.focus());
  }

  return (
    <div className="saved">
      <h2 id="screen-saved" className="screen-title" tabIndex={-1} ref={headingRef}>Saved plans</h2>

      {error && <p className="notice" role="alert">{error}</p>}
      {!plans && !error && <p className="muted">Loading saved plans…</p>}

      {plans?.length === 0 && (
        <p className="saved-empty">
          No saved plans yet. Plan your day and save it to see it here. <a href="#/plan">Plan my day</a>
        </p>
      )}

      {plans && plans.length > 0 && (
        <ul className="saved-list">
          {plans.map((plan) => {
            const open = expanded === plan.id;
            const detail = details[plan.id];
            return (
              <li key={plan.id} className={`saved-item${open ? " saved-item--open" : ""}`}>
                <button
                  type="button"
                  className="saved-row"
                  aria-expanded={open}
                  aria-controls={`saved-plan-${plan.id}`}
                  onClick={() => toggle(plan.id)}
                >
                  <span className="saved-date">{formatDate(plan.created_at)}</span>
                  <span className="saved-numbers">
                    {NUMBERS.map(({ key, unit, word }) => (
                      <span key={key} className="saved-number">
                        <span className="number" style={{ color: `var(--${key})` }}>{formatNumber(plan.macros[key])}</span>
                        <span className="saved-unit"> {unit}</span>
                        {word && <span className="visually-hidden"> {word}</span>}
                        <span className="visually-hidden">,</span>
                      </span>
                    ))}
                  </span>
                  <span className="saved-miss muted">{missInWords(plan.macros, plan.targets)}</span>
                </button>

                {open && (
                  <div id={`saved-plan-${plan.id}`} className="saved-detail">
                    {detail?.kind === "loading" && <p className="muted">Loading plan…</p>}
                    {detail?.kind === "error" && <p className="form-error" role="alert">{detail.message}</p>}
                    {detail?.kind === "ok" && (
                      <>
                        <p className="muted saved-targets">
                          Targets: {formatNumber(detail.plan.targets.calories)} kcal · {formatNumber(detail.plan.targets.protein)} g protein ·{" "}
                          {formatNumber(detail.plan.targets.carbs)} g carbs · {formatNumber(detail.plan.targets.fat)} g fat
                        </p>
                        <Timeline meals={detail.plan.meals} />
                      </>
                    )}

                    <div className="saved-actions">
                      {confirming === plan.id ? (
                        <div className="saved-confirm" role="group" aria-labelledby={`confirm-${plan.id}`}>
                          <span id={`confirm-${plan.id}`}>Delete this plan?</span>
                          <button type="button" className="button-danger" onClick={() => void confirmDelete(plan.id)} disabled={deleting}>
                            {deleting ? "Deleting…" : "Delete"}
                          </button>
                          <button type="button" ref={keepRef} onClick={keep} disabled={deleting}>Keep</button>
                        </div>
                      ) : (
                        <button type="button" className="link-button" ref={deleteRef} onClick={() => setConfirming(plan.id)}>
                          Delete
                        </button>
                      )}
                      {deleteError && <p className="form-error" role="alert">{deleteError}</p>}
                    </div>
                  </div>
                )}
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}
