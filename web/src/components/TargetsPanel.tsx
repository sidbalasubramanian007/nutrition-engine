import type { FormEvent } from "react";
import type { Activity, DailyTargets, Gender, Goal } from "../api.ts";
import { formatNumber } from "../format.ts";
import Segmented from "./Segmented.tsx";
import "./TargetsPanel.css";

export type TargetsMode = "calculate" | "own";

export interface Profile {
  age: string;
  weight: string;
  heightFt: string;
  heightIn: string;
  sex: Gender;
  activity: Activity;
  goal: Goal;
}

export interface OwnTargets {
  calories: string;
  protein: string;
  carbs: string;
  fat: string;
}

const ACTIVITIES: Activity[] = ["Sedentary", "Lightly Active", "Moderately Active", "Very Active"];
const ACTIVITY_LABELS: Record<Activity, string> = {
  Sedentary: "Sedentary",
  "Lightly Active": "Lightly active",
  "Moderately Active": "Moderately active",
  "Very Active": "Very active",
};
const GOALS: Goal[] = ["Maintenance", "Bulking", "Cutting"];

interface Props {
  id: string;
  collapsed: boolean;
  mode: TargetsMode;
  onModeChange: (mode: TargetsMode) => void;
  profile: Profile;
  onProfileChange: (profile: Profile) => void;
  ownTargets: OwnTargets;
  onOwnTargetsChange: (targets: OwnTargets) => void;
  calculated: DailyTargets | null;
  onlyVerified: boolean;
  onOnlyVerifiedChange: (value: boolean) => void;
  onSubmit: () => void;
  loading: boolean;
  unreachable: boolean;
  dbDown: boolean;
  error: string | null;
}

function NumberField({
  id, label, value, onChange, min, max, step = "1",
}: { id: string; label: string; value: string; onChange: (v: string) => void; min: number; max: number; step?: string }) {
  return (
    <div className="field">
      <label htmlFor={id}>{label}</label>
      <input
        id={id}
        type="number"
        inputMode="decimal"
        min={min}
        max={max}
        step={step}
        value={value}
        onChange={(e) => onChange(e.target.value)}
      />
    </div>
  );
}

export default function TargetsPanel(props: Props) {
  const { profile, ownTargets } = props;
  const setProfile = (patch: Partial<Profile>) => props.onProfileChange({ ...profile, ...patch });
  const setOwn = (patch: Partial<OwnTargets>) => props.onOwnTargetsChange({ ...ownTargets, ...patch });

  const submit = (event: FormEvent) => {
    event.preventDefault();
    props.onSubmit();
  };

  return (
    <section id={props.id} className={`targets panel${props.collapsed ? " targets--collapsed" : ""}`} aria-labelledby="targets-heading">
      <h2 id="targets-heading" className="panel-heading">Targets</h2>

      {props.unreachable ? (
        <p className="notice" role="alert">The planner can't reach the server. Start the API and try again.</p>
      ) : props.dbDown ? (
        <p className="notice" role="alert">The server is running but can't reach its database.</p>
      ) : null}

      <Segmented
        name="targets-mode"
        legend="How to set your targets"
        options={[{ value: "calculate", label: "Calculate for me" }, { value: "own", label: "Set my own" }]}
        value={props.mode}
        onChange={props.onModeChange}
      />

      <form className="targets-form" onSubmit={submit} noValidate>
        {props.mode === "calculate" ? (
          <>
            <div className="field-grid">
              <NumberField id="age" label="Age" value={profile.age} onChange={(age) => setProfile({ age })} min={13} max={100} />
              <NumberField id="weight" label="Weight (lbs)" value={profile.weight} onChange={(weight) => setProfile({ weight })} min={70} max={700} step="any" />
            </div>
            <fieldset className="field-group">
              <legend>Height</legend>
              <div className="field-grid">
                <NumberField id="height-ft" label="Feet" value={profile.heightFt} onChange={(heightFt) => setProfile({ heightFt })} min={3} max={8} />
                <NumberField id="height-in" label="Inches" value={profile.heightIn} onChange={(heightIn) => setProfile({ heightIn })} min={0} max={11.9} step="any" />
              </div>
            </fieldset>
            <div className="field">
              <label htmlFor="sex">Sex</label>
              <select id="sex" value={profile.sex} onChange={(e) => setProfile({ sex: e.target.value as Gender })}>
                <option value="Male">Male</option>
                <option value="Female">Female</option>
              </select>
            </div>
            <div className="field">
              <label htmlFor="activity">Activity</label>
              <select id="activity" value={profile.activity} onChange={(e) => setProfile({ activity: e.target.value as Activity })}>
                {ACTIVITIES.map((a) => <option key={a} value={a}>{ACTIVITY_LABELS[a]}</option>)}
              </select>
            </div>
            <div className="field">
              <label htmlFor="goal">Goal</label>
              <select id="goal" value={profile.goal} onChange={(e) => setProfile({ goal: e.target.value as Goal })}>
                {GOALS.map((g) => <option key={g} value={g}>{g}</option>)}
              </select>
            </div>
            {props.calculated && (
              <p className="calculated muted">
                Your targets: {formatNumber(props.calculated.calories)} kcal · {formatNumber(props.calculated.protein)} g protein ·{" "}
                {formatNumber(props.calculated.carbs)} g carbs · {formatNumber(props.calculated.fat)} g fat
              </p>
            )}
          </>
        ) : (
          <div className="field-grid">
            <NumberField id="calories" label="Calories (kcal)" value={ownTargets.calories} onChange={(calories) => setOwn({ calories })} min={1000} max={6000} />
            <NumberField id="protein" label="Protein (g)" value={ownTargets.protein} onChange={(protein) => setOwn({ protein })} min={0} max={500} />
            <NumberField id="carbs" label="Carbs (g)" value={ownTargets.carbs} onChange={(carbs) => setOwn({ carbs })} min={0} max={1000} />
            <NumberField id="fat" label="Fat (g)" value={ownTargets.fat} onChange={(fat) => setOwn({ fat })} min={0} max={400} />
          </div>
        )}

        <label className="checkbox">
          <input type="checkbox" checked={props.onlyVerified} onChange={(e) => props.onOnlyVerifiedChange(e.target.checked)} />
          <span>
            Only verified foods
            <span className="checkbox-hint muted">Leaves out foods whose macros are estimates.</span>
          </span>
        </label>

        {props.error && <p className="form-error" role="alert">{props.error}</p>}

        <button type="submit" className="button-primary" disabled={props.loading}>
          {props.loading ? "Planning…" : "Plan my day"}
        </button>
      </form>
    </section>
  );
}
