import type { DailyMeal, Plan } from "../api.ts";
import type { SaveState } from "../usePlanner.ts";
import { LockIcon, RemoveIcon } from "./icons.tsx";
import Timeline from "./Timeline.tsx";
import "./DayTimeline.css";


interface Props {
  plan: Plan | null;
  infeasible: { reason: string; fix: string } | null;
  loading: boolean;
  lockedCount: number;
  removedCount: number;
  isLocked: (name: string, meal: string, servings: number) => boolean;
  /** Foods removed since this plan was made (shown when a re-plan came back infeasible) */
  removed: string[];
  onToggleLock: (name: string, meal: DailyMeal, servings: number) => void;
  onRemove: (name: string) => void;
  onClear: () => void;
  onReplan: () => void;
  saveState: SaveState;
  onSave: () => void;
  /** Solver status in words, shown here only on narrow screens (where the scoreboard is a strip) */
  statusText: string | null;
}

export default function DayTimeline(props: Props) {
  const { plan } = props;
  const hasConstraints = props.lockedCount > 0 || props.removedCount > 0;

  return (
    <section className="day" aria-labelledby="day-heading" aria-busy={props.loading}>
      <div className="day-toolbar">
        <h2 id="day-heading" className="panel-heading">Your day</h2>
        {(plan || props.infeasible) && (
          <button type="button" onClick={props.onReplan} disabled={props.loading}>
            {props.loading ? "Planning…" : "Re-plan"}
          </button>
        )}
      </div>

      {hasConstraints && (
        <p className="constraints muted">
          {[props.lockedCount > 0 && `${props.lockedCount} locked`, props.removedCount > 0 && `${props.removedCount} removed`]
            .filter(Boolean)
            .join(" · ")}{" "}
          ·{" "}
          <button type="button" className="link-button" onClick={props.onClear}>
            Clear
          </button>
        </p>
      )}

      {props.statusText && <p className="day-status muted">{props.statusText}</p>}

      {props.infeasible && (
        <div className="infeasible" role="alert">
          <p>{props.infeasible.reason}</p>
          <p className="infeasible-fix">{props.infeasible.fix}</p>
          {plan && <p className="muted">Your last plan is below.</p>}
        </div>
      )}

      {!plan && !props.infeasible && <p className="empty">Set your targets and plan your day.</p>}

      {plan && (
        <Timeline
          meals={plan.meals}
          loading={props.loading}
          rowClass={(item, meal) =>
            [props.isLocked(item.name, meal.name, item.servings) && "food--locked", props.removed.includes(item.name) && "food--removed"]
              .filter(Boolean)
              .join(" ")
          }
          rowNote={(item) => (props.removed.includes(item.name) ? ", removed" : "")}
          actions={(item, meal) => {
            const mealName = meal.name as DailyMeal;
            const locked = props.isLocked(item.name, mealName, item.servings);
            return (
              <>
                <button
                  type="button"
                  className="icon-button"
                  aria-label={`Lock ${item.name} in ${meal.name.toLowerCase()}`}
                  aria-pressed={locked}
                  onClick={() => props.onToggleLock(item.name, mealName, item.servings)}
                >
                  <LockIcon filled={locked} />
                </button>
                {!props.removed.includes(item.name) && (
                  <button
                    type="button"
                    className="icon-button"
                    aria-label={`Remove ${item.name} and re-plan`}
                    onClick={() => props.onRemove(item.name)}
                  >
                    <RemoveIcon />
                  </button>
                )}
              </>
            );
          }}
        />
      )}

      {plan && (
        <div className="save-row">
          <button
            type="button"
            onClick={props.onSave}
            disabled={props.loading || props.saveState.kind === "saving" || props.saveState.kind === "saved"}
          >
            {props.saveState.kind === "saved" ? "Saved" : props.saveState.kind === "saving" ? "Saving…" : "Save plan"}
          </button>
          <span role="status" className="muted">
            {props.saveState.kind === "saved" ? `Saved as plan #${props.saveState.id}.` : ""}
          </span>
          {props.saveState.kind === "error" && <p className="form-error" role="alert">{props.saveState.message}</p>}
        </div>
      )}
    </section>
  );
}
