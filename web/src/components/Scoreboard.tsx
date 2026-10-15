import type { CSSProperties } from "react";
import type { DailyTargets, Macros } from "../api.ts";
import { barFill, BAR_SCALE, deviationText, formatNumber, type MacroKey } from "../format.ts";
import "./Scoreboard.css";

const ROWS: { key: MacroKey; label: string; unit: string }[] = [
  { key: "calories", label: "Calories", unit: "kcal" },
  { key: "protein", label: "Protein", unit: "g" },
  { key: "carbs", label: "Carbs", unit: "g" },
  { key: "fat", label: "Fat", unit: "g" },
];

const TICK_POSITION = `${100 / BAR_SCALE}%`;

interface Props {
  macros: Macros | null;
  targets: DailyTargets | null;
  loading: boolean;
  statusText: string | null;
  statusDetail: string | null;
}

export default function Scoreboard({ macros, targets, loading, statusText, statusDetail }: Props) {
  return (
    <aside className={`scoreboard${loading ? " scoreboard--loading" : ""}`} aria-labelledby="scoreboard-heading">
      <h2 id="scoreboard-heading" className="panel-heading scoreboard-heading">Your numbers</h2>
      <dl className="score-rows">
        {ROWS.map(({ key, label, unit }) => {
          const achieved = macros?.[key];
          const target = targets?.[key];
          const have = achieved !== undefined && target !== undefined;
          return (
            <div key={key} className="score-row" style={{ "--macro": `var(--${key})` } as CSSProperties}>
              <dt className="score-label">{label}</dt>
              <dd className="score-value">
                <span className="number score-number">{have ? formatNumber(achieved) : "–"}</span>
                <span className="score-unit">{unit}</span>
              </dd>
              <dd className="score-bar" aria-hidden="true">
                <span className="score-fill" style={{ width: `${have ? barFill(achieved, target) : 0}%` }} />
                <span className="score-tick" style={{ left: TICK_POSITION }} />
              </dd>
              <dd className="score-deviation">
                {have ? deviationText(achieved, target, unit) : "No plan yet"}
                {have && <span className="visually-hidden"> (target {formatNumber(target)} {unit})</span>}
              </dd>
            </div>
          );
        })}
      </dl>
      {statusText && (
        <p className="score-status">
          {statusText}
          {statusDetail && <span className="muted"> · {statusDetail}</span>}
        </p>
      )}
    </aside>
  );
}
