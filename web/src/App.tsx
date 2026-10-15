import { useState } from "react";
import { calculateTargets, type DailyTargets } from "./api.ts";
import DayTimeline from "./components/DayTimeline.tsx";
import Scoreboard from "./components/Scoreboard.tsx";
import TargetsPanel, { type OwnTargets, type Profile, type TargetsMode } from "./components/TargetsPanel.tsx";
import { formatNumber, suggestFix } from "./format.ts";
import { describeError, PLAN_TIME_LIMIT, usePlanner } from "./usePlanner.ts";
import "./App.css";

const DEFAULT_PROFILE: Profile = {
  age: "30",
  weight: "170",
  heightFt: "5",
  heightIn: "10",
  sex: "Male",
  activity: "Moderately Active",
  goal: "Maintenance",
};
const DEFAULT_OWN: OwnTargets = { calories: "2800", protein: "170", carbs: "390", fat: "68" };

// Same limits as the API's DailyTargets, checked here so the message can be friendly
const LIMITS: Record<keyof DailyTargets, [string, number, number, string]> = {
  calories: ["Calories", 1000, 6000, "kcal"],
  protein: ["Protein", 0, 500, "g"],
  carbs: ["Carbs", 0, 1000, "g"],
  fat: ["Fat", 0, 400, "g"],
};

function parseOwnTargets(own: OwnTargets): DailyTargets | string {
  const result = {} as DailyTargets;
  for (const key of Object.keys(LIMITS) as (keyof DailyTargets)[]) {
    const [label, min, max, unit] = LIMITS[key];
    const value = Number(own[key]);
    if (own[key].trim() === "" || !Number.isFinite(value) || value < min || value > max) {
      return `${label} must be between ${formatNumber(min)} and ${formatNumber(max)} ${unit}.`;
    }
    result[key] = value;
  }
  return result;
}

function profileError(p: Profile): string | null {
  const checks: [string, string, number, number][] = [
    ["Age", p.age, 13, 100],
    ["Weight", p.weight, 70, 700],
    ["Height (feet)", p.heightFt, 3, 8],
    ["Height (inches)", p.heightIn, 0, 11.99],
  ];
  for (const [label, raw, min, max] of checks) {
    const value = Number(raw);
    if (raw.trim() === "" || !Number.isFinite(value) || value < min || value > max) {
      return `${label} must be between ${min} and ${Math.floor(max)}.`;
    }
  }
  return null;
}

export default function App() {
  const planner = usePlanner();
  const [mode, setMode] = useState<TargetsMode>("calculate");
  const [profile, setProfile] = useState<Profile>(DEFAULT_PROFILE);
  const [ownTargets, setOwnTargets] = useState<OwnTargets>(DEFAULT_OWN);
  const [calculated, setCalculated] = useState<DailyTargets | null>(null);
  const [onlyVerified, setOnlyVerified] = useState(false);
  const [targetsOpen, setTargetsOpen] = useState(false);
  const [calculating, setCalculating] = useState(false);

  /** The targets to plan for: calculated from the profile, or the user's own. */
  async function resolveTargets(): Promise<DailyTargets | null> {
    if (mode === "own") {
      const parsed = parseOwnTargets(ownTargets);
      if (typeof parsed === "string") {
        planner.setError(parsed);
        return null;
      }
      return parsed;
    }
    const invalid = profileError(profile);
    if (invalid) {
      planner.setError(invalid);
      return null;
    }
    setCalculating(true);
    try {
      const targets = await calculateTargets({
        age: Number(profile.age),
        weight_lbs: Number(profile.weight),
        height_ft: Number(profile.heightFt),
        height_in: Number(profile.heightIn),
        gender: profile.sex,
        activity: profile.activity,
        goal: profile.goal,
      });
      setCalculated(targets);
      // Switching to "Set my own" starts from the calculated numbers
      setOwnTargets({
        calories: String(targets.calories),
        protein: String(targets.protein),
        carbs: String(targets.carbs),
        fat: String(targets.fat),
      });
      if (targets.calories < LIMITS.calories[1]) {
        planner.setError(`These details give ${formatNumber(targets.calories)} kcal, below the planner's 1,000 kcal minimum. Set your own targets instead.`);
        return null;
      }
      return targets;
    } catch (e) {
      planner.setError(describeError(e).message);
      return null;
    } finally {
      setCalculating(false);
    }
  }

  async function planDay() {
    const targets = await resolveTargets();
    if (targets) await planner.planDay(targets, onlyVerified);
  }

  const busy = planner.loading || calculating;
  const plan = planner.plan;
  const statusText = planner.infeasibleReason
    ? "No plan fits the current settings"
    : plan?.status === "optimal"
      ? "Best possible plan"
      : plan?.status === "feasible"
        ? `Best plan found in ${PLAN_TIME_LIMIT}s`
        : null;
  const statusDetail = plan && !planner.infeasibleReason ? `solved in ${plan.solve_time.toFixed(2)} s` : null;
  const infeasible = planner.infeasibleReason
    ? {
        reason: planner.infeasibleReason,
        fix: suggestFix(planner.infeasibleReason, {
          locked: planner.locked.length,
          removed: planner.excluded.length,
          onlyVerified,
        }),
      }
    : null;

  return (
    <div className="page">
      <header className="page-header">
        <h1 className="page-title">Nutrition engine</h1>
        <p className="muted">Plan a day of meals that hits your calories, protein, carbs and fat.</p>
      </header>

      <main className="planner">
        <div className="planner-score">
          <Scoreboard
            macros={plan?.macros ?? null}
            targets={planner.planTargets}
            loading={planner.loading}
            statusText={statusText}
            statusDetail={statusDetail}
          />
        </div>

        <button
          type="button"
          className="targets-toggle"
          aria-expanded={targetsOpen}
          aria-controls="targets-panel"
          onClick={() => setTargetsOpen((open) => !open)}
        >
          {targetsOpen ? "Hide targets" : "Edit targets"}
        </button>

        <div className="planner-targets">
          <TargetsPanel
            id="targets-panel"
            collapsed={!targetsOpen}
            mode={mode}
            onModeChange={setMode}
            profile={profile}
            onProfileChange={setProfile}
            ownTargets={ownTargets}
            onOwnTargetsChange={setOwnTargets}
            calculated={calculated}
            onlyVerified={onlyVerified}
            onOnlyVerifiedChange={setOnlyVerified}
            onSubmit={() => void planDay()}
            loading={busy}
            unreachable={planner.unreachable}
            dbDown={planner.dbDown}
            error={planner.error}
          />
        </div>

        <div className="planner-day">
          <DayTimeline
            plan={plan}
            infeasible={infeasible}
            loading={busy}
            lockedCount={planner.locked.length}
            removedCount={planner.excluded.length}
            isLocked={planner.isLocked}
            removed={planner.excluded}
            onToggleLock={planner.toggleLock}
            onRemove={planner.removeFood}
            onClear={planner.clearConstraints}
            onReplan={() => void planDay()}
            saveState={planner.saveState}
            onSave={() => void planner.save()}
            statusText={statusText && (statusDetail ? `${statusText} · ${statusDetail}` : statusText)}
          />
        </div>
      </main>
    </div>
  );
}
