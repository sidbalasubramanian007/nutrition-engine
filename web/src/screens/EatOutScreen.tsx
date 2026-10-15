import { useEffect, useMemo, useState } from "react";
import { getFoods, optimizeRestaurantOrder, type Food, type Macros, type MealTargets, type Plan } from "../api.ts";
import { MacroLabel } from "../components/Timeline.tsx";
import Scoreboard from "../components/Scoreboard.tsx";
import Segmented from "../components/Segmented.tsx";
import { useDayTargets } from "../dayTargets.tsx";
import { formatNumber } from "../format.ts";
import { describeError } from "../usePlanner.ts";
import "./EatOutScreen.css";

type Mode = "build" | "find";
type Quantities = Record<string, number>;
type TargetFields = Record<keyof MealTargets, string>;

const GROUPS = [
  { type: "base", heading: "Bases" },
  { type: "protein", heading: "Proteins" },
  { type: "beans", heading: "Beans" },
  { type: "topping", heading: "Toppings" },
  { type: "sauce", heading: "Sauces" },
] as const;

// Same limits as the API's MealTargets
const LIMITS: Record<keyof MealTargets, [string, number, number, string]> = {
  calories: ["Calories", 100, 3000, "kcal"],
  protein: ["Protein", 0, 300, "g"],
  carbs: ["Carbs", 0, 500, "g"],
  fat: ["Fat", 0, 200, "g"],
};
const MACRO_KEYS: (keyof Macros)[] = ["calories", "protein", "carbs", "fat", "fiber"];

/** "Chipotle Chicken" -> "Chicken" on Chipotle's menu. */
function displayName(name: string, restaurant: string): string {
  return name.startsWith(`${restaurant} `) ? name.slice(restaurant.length + 1) : name;
}

/** Toppings and sauces are single servings; everything else up to 2 (or the item's own limit). */
function servingCap(food: Food): number {
  return food.component_type === "topping" || food.component_type === "sauce" ? 1 : Math.min(2, food.max_servings);
}

function scaled(food: Food, servings: number): Macros {
  return Object.fromEntries(MACRO_KEYS.map((k) => [k, food[k] * servings])) as unknown as Macros;
}

function thirdOf(day: MealTargets): TargetFields {
  return {
    calories: String(Math.round(day.calories / 3)),
    protein: String(Math.round(day.protein / 3)),
    carbs: String(Math.round(day.carbs / 3)),
    fat: String(Math.round(day.fat / 3)),
  };
}

function parseTargets(fields: TargetFields): MealTargets | string {
  const result = {} as MealTargets;
  for (const key of Object.keys(LIMITS) as (keyof MealTargets)[]) {
    const [label, min, max, unit] = LIMITS[key];
    const value = Number(fields[key]);
    if (fields[key].trim() === "" || !Number.isFinite(value) || value < min || value > max) {
      return `${label} must be between ${formatNumber(min)} and ${formatNumber(max)} ${unit}.`;
    }
    result[key] = value;
  }
  return result;
}

/** What a manually built order is missing under the structure rules, or null. */
function missingParts(menu: Food[], quantities: Quantities): string | null {
  const chosen = menu.filter((f) => (quantities[f.name] ?? 0) > 0);
  if (chosen.length === 0) return null;
  const missing = (["base", "protein"] as const).filter((type) => !chosen.some((f) => f.component_type === type));
  if (missing.length === 0) return null;
  return `Your order has no ${missing.join(" or ")} yet.`;
}

export default function EatOutScreen() {
  const { dayTargets } = useDayTargets();
  const [foods, setFoods] = useState<Food[] | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [restaurant, setRestaurant] = useState<string | null>(null);
  const [mode, setMode] = useState<Mode>("build");
  const [quantities, setQuantities] = useState<Record<string, Quantities>>({});
  const [fields, setFields] = useState<TargetFields>(() => thirdOf(dayTargets));
  const [fieldsEdited, setFieldsEdited] = useState(false);
  const [result, setResult] = useState<{ restaurant: string; plan: Plan } | null>(null);
  const [finding, setFinding] = useState(false);
  const [findError, setFindError] = useState<string | null>(null);
  const [announcement, setAnnouncement] = useState("");

  useEffect(() => {
    const controller = new AbortController();
    getFoods({}, controller.signal)
      .then(setFoods)
      .catch((e: unknown) => {
        if (e instanceof DOMException && e.name === "AbortError") return;
        setLoadError(describeError(e).message);
      });
    return () => controller.abort();
  }, []);

  // Follow the planner's targets until the user edits these
  useEffect(() => {
    if (!fieldsEdited) setFields(thirdOf(dayTargets));
  }, [dayTargets, fieldsEdited]);

  // Restaurants come from the data, so new ones appear automatically
  const restaurants = useMemo(
    () => [...new Set((foods ?? []).map((f) => f.location).filter((l) => l !== "Grocery"))],
    [foods],
  );
  const current = restaurant ?? restaurants[0] ?? null;
  const menu = useMemo(() => (foods ?? []).filter((f) => f.location === current), [foods, current]);
  const orderQuantities = current ? quantities[current] ?? {} : {};

  const targets = parseTargets(fields);
  const validTargets = typeof targets === "string" ? null : targets;
  const currentResult = result && result.restaurant === current ? result.plan : null;

  const buildTotals = useMemo(() => {
    const totals: Macros = { calories: 0, protein: 0, carbs: 0, fat: 0, fiber: 0 };
    for (const food of menu) {
      const servings = orderQuantities[food.name] ?? 0;
      for (const key of MACRO_KEYS) totals[key] += food[key] * servings;
    }
    return totals;
  }, [menu, orderQuantities]);

  const shownMacros = mode === "build" ? buildTotals : currentResult?.macros ?? null;
  const nothingChosen = menu.every((f) => (orderQuantities[f.name] ?? 0) === 0);
  const emptyMessage =
    mode === "build" && nothingChosen
      ? "Add items to see how this order fits your targets."
      : mode === "find" && !currentResult
        ? "Find your best order to see how it fits your targets."
        : null;
  const statusText =
    mode === "find" && currentResult
      ? currentResult.status === "optimal"
        ? "Best possible order"
        : currentResult.status === "feasible"
          ? "Best order found in 1s"
          : "No order fits these targets"
      : null;
  const statusDetail = mode === "find" && currentResult && currentResult.status !== "infeasible"
    ? `solved in ${currentResult.solve_time.toFixed(2)} s`
    : null;

  function setServings(food: Food, servings: number) {
    if (!current) return;
    const next = Math.max(0, Math.min(servingCap(food), servings));
    setQuantities((all) => ({ ...all, [current]: { ...(all[current] ?? {}), [food.name]: next } }));
    setAnnouncement(`${displayName(food.name, current)}: ${next}`);
  }

  async function findBestOrder() {
    if (!current) return;
    if (typeof targets === "string") {
      setFindError(targets);
      return;
    }
    setFinding(true);
    setFindError(null);
    try {
      const plan = await optimizeRestaurantOrder({ restaurant: current, targets });
      setResult({ restaurant: current, plan });
    } catch (e) {
      setFindError(describeError(e).message);
    } finally {
      setFinding(false);
    }
  }

  function applyFoundOrder() {
    if (!current || !currentResult) return;
    const filled: Quantities = {};
    for (const item of currentResult.meals.flatMap((m) => m.items)) filled[item.name] = item.servings;
    setQuantities((all) => ({ ...all, [current]: filled }));
    setMode("build");
    setAnnouncement("Order copied to Build my order");
  }

  const missing = mode === "build" ? missingParts(menu, orderQuantities) : null;

  return (
    <div className="eatout">
      <div className="score-slot eatout-score">
        <Scoreboard
          macros={shownMacros}
          targets={validTargets}
          loading={finding}
          statusText={statusText}
          statusDetail={statusDetail}
          emptyMessage={emptyMessage}
        />
      </div>

      <div className="eatout-main">
        <h2 id="screen-eat-out" className="screen-title" tabIndex={-1}>Eat out</h2>

        {loadError && <p className="notice" role="alert">{loadError}</p>}
        {!foods && !loadError && <p className="muted">Loading menus…</p>}
        {foods && restaurants.length === 0 && <p className="muted">No restaurant menus are loaded.</p>}

        {current && (
          <>
            <div className="eatout-controls">
              <Segmented
                name="restaurant"
                legend="Restaurant"
                options={restaurants.map((r) => ({ value: r, label: r }))}
                value={current}
                onChange={setRestaurant}
              />
              <Segmented
                name="eatout-mode"
                legend="What to do"
                options={[{ value: "build", label: "Build my order" }, { value: "find", label: "Find my best order" }] as const}
                value={mode}
                onChange={setMode}
              />
            </div>

            {mode === "build" ? (
              <section className="menu" aria-labelledby="menu-heading">
                <div className="menu-header">
                  <h3 id="menu-heading" className="panel-heading">{current} menu</h3>
                  <p className="muted menu-note">Macros are per serving.</p>
                </div>
                {missing && <p className="menu-missing">{missing}</p>}
                {GROUPS.map(({ type, heading }) => {
                  const items = menu.filter((f) => f.component_type === type);
                  if (items.length === 0) return null;
                  return (
                    <div key={type} className="menu-group">
                      <h4 className="menu-group-heading">{heading}</h4>
                      <ul className="menu-rows">
                        {items.map((food) => {
                          const servings = orderQuantities[food.name] ?? 0;
                          const cap = servingCap(food);
                          const name = displayName(food.name, current);
                          return (
                            <li key={food.name} className={`menu-row${servings > 0 ? " menu-row--chosen" : ""}`}>
                              <span className="menu-name">{name}</span>
                              <MacroLabel category={food.category} macros={scaled(food, 1)} />
                              <span className="stepper" role="group" aria-label={`${name} servings`}>
                                <button
                                  type="button"
                                  className="stepper-button"
                                  aria-label={`Remove one ${name}`}
                                  aria-disabled={servings === 0}
                                  onClick={() => servings > 0 && setServings(food, servings - 1)}
                                >
                                  −
                                </button>
                                <span className="stepper-count number">{servings}</span>
                                <button
                                  type="button"
                                  className="stepper-button"
                                  aria-label={`Add one ${name}`}
                                  aria-disabled={servings >= cap}
                                  onClick={() => servings < cap && setServings(food, servings + 1)}
                                >
                                  +
                                </button>
                              </span>
                            </li>
                          );
                        })}
                      </ul>
                    </div>
                  );
                })}
              </section>
            ) : (
              <section className="find" aria-labelledby="find-heading">
                <h3 id="find-heading" className="panel-heading">Targets for this meal</h3>
                <p className="muted menu-note">Prefilled with a third of your day's targets.</p>
                <form
                  className="find-form"
                  noValidate
                  onSubmit={(e) => {
                    e.preventDefault();
                    void findBestOrder();
                  }}
                >
                  <div className="field-grid find-fields">
                    {(Object.keys(LIMITS) as (keyof MealTargets)[]).map((key) => {
                      const [label, min, max, unit] = LIMITS[key];
                      return (
                        <div key={key} className="field">
                          <label htmlFor={`meal-${key}`}>{`${label} (${unit})`}</label>
                          <input
                            id={`meal-${key}`}
                            type="number"
                            inputMode="decimal"
                            min={min}
                            max={max}
                            value={fields[key]}
                            onChange={(e) => {
                              setFieldsEdited(true);
                              setFields((f) => ({ ...f, [key]: e.target.value }));
                            }}
                          />
                        </div>
                      );
                    })}
                  </div>
                  {findError && <p className="form-error" role="alert">{findError}</p>}
                  <button type="submit" className="button-primary" disabled={finding}>
                    {finding ? "Finding…" : "Find my best order"}
                  </button>
                </form>

                {currentResult?.status === "infeasible" && (
                  <p className="infeasible" role="alert">{currentResult.message}</p>
                )}
                {currentResult && currentResult.status !== "infeasible" && (
                  <div className="find-result">
                    <h3 className="panel-heading">Your best order</h3>
                    <ul className="menu-rows">
                      {currentResult.meals.flatMap((m) => m.items).map((item) => (
                        <li key={item.name} className="menu-row menu-row--chosen">
                          <span className="menu-name">
                            <span className="food-servings">{item.servings} ×</span> {displayName(item.name, current)}
                          </span>
                          <MacroLabel category={item.category} macros={item.macros} />
                          <span className="food-kcal">{formatNumber(item.macros.calories)} kcal</span>
                        </li>
                      ))}
                    </ul>
                    <button type="button" onClick={applyFoundOrder}>Use this order</button>
                  </div>
                )}
              </section>
            )}
          </>
        )}
        <p className="visually-hidden" role="status" aria-live="polite">{announcement}</p>
      </div>
    </div>
  );
}
