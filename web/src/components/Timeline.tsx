import type { ReactNode } from "react";
import type { MealGroup, PlanItem } from "../api.ts";
import { featuredMacro, formatNumber, MACRO_WORDS } from "../format.ts";
import "./Timeline.css";

const MEAL_ORDER = ["Breakfast", "Lunch", "Dinner", "Snack", "Order"];

/** A food's role macro, e.g. "31 g protein", in that macro's color. grams is already for the servings shown. */
export function MacroLabel({ category, macros, muted = false }: { category: string; macros: PlanItem["macros"]; muted?: boolean }) {
  const macro = featuredMacro(category, macros);
  return (
    <span className={`food-macro food-macro--${muted ? "muted" : macro}`}>
      {formatNumber(macros[macro])} g {MACRO_WORDS[macro]}
    </span>
  );
}

interface Props {
  meals: MealGroup[];
  loading?: boolean;
  /** Extra classes for a row, e.g. "food--locked" */
  rowClass?: (item: PlanItem, meal: MealGroup) => string;
  /** Visually hidden suffix for a row's name, e.g. ", removed" */
  rowNote?: (item: PlanItem, meal: MealGroup) => string;
  /** Buttons at the end of a row; omit for a read-only timeline */
  actions?: (item: PlanItem, meal: MealGroup) => ReactNode;
}

/** Meals as a vertical timeline: meal name on the left, its foods stacked on the right. */
export default function Timeline({ meals, loading = false, rowClass, rowNote, actions }: Props) {
  const ordered = [...meals].sort((a, b) => MEAL_ORDER.indexOf(a.name) - MEAL_ORDER.indexOf(b.name));
  return (
    <ol className={`timeline${loading ? " timeline--loading" : ""}${actions ? "" : " timeline--readonly"}`}>
      {ordered.map((meal) => (
        <li key={meal.name} className="meal">
          <h3 className="meal-name">{meal.name}</h3>
          <ul className="foods">
            {meal.items.map((item) => {
              const extra = rowClass?.(item, meal) ?? "";
              const note = rowNote?.(item, meal) ?? "";
              return (
                <li key={item.name} className={`food${extra ? ` ${extra}` : ""}`}>
                  <span className="food-name">
                    <span className="food-servings">{item.servings} ×</span> {item.name}
                    {note && <span className="visually-hidden">{note}</span>}
                  </span>
                  <MacroLabel category={item.category} macros={item.macros} muted={extra.includes("food--removed")} />
                  <span className="food-kcal">{formatNumber(item.macros.calories)} kcal</span>
                  {actions && <span className="food-actions">{actions(item, meal)}</span>}
                </li>
              );
            })}
          </ul>
        </li>
      ))}
    </ol>
  );
}
