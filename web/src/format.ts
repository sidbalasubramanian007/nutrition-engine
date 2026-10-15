import type { Macros } from "./api.ts";

const integer = new Intl.NumberFormat("en-US", { maximumFractionDigits: 0 });

export function formatNumber(value: number): string {
  return integer.format(Math.round(value));
}

export type MacroKey = "calories" | "protein" | "carbs" | "fat";

/** The macro contributing the most calories: protein and carbs at 4 kcal/g, fat at 9. */
export function dominantMacro(macros: Macros): Exclude<MacroKey, "calories"> {
  const energy = { protein: macros.protein * 4, carbs: macros.carbs * 4, fat: macros.fat * 9 };
  return (Object.keys(energy) as (keyof typeof energy)[]).reduce((best, key) => (energy[key] > energy[best] ? key : best));
}

/**
 * The macro a food is in the plan for: protein for lean proteins, carbs for staples,
 * otherwise (snacks, fats) whichever macro contributes the most calories.
 */
export function featuredMacro(category: string, macros: Macros): Exclude<MacroKey, "calories"> {
  if (category === "lean_protein") return "protein";
  if (category === "staple") return "carbs";
  return dominantMacro(macros);
}

/** "on target" within 1%, otherwise "+12 g over" / "8 g under". */
export function deviationText(achieved: number, target: number, unit: string): string {
  const diff = achieved - target;
  const withinOnePercent = target > 0 ? Math.abs(diff) <= target * 0.01 : Math.abs(diff) < 0.5;
  if (withinOnePercent) return "on target";
  const amount = formatNumber(Math.abs(diff));
  return diff > 0 ? `+${amount} ${unit} over` : `${amount} ${unit} under`;
}

/** Fill width as a % of the bar, whose full width is 130% of the target (the tick sits at 100%). */
export const BAR_SCALE = 1.3;
export function barFill(achieved: number, target: number): number {
  const ratio = target > 0 ? achieved / target : achieved > 0 ? BAR_SCALE : 0;
  return (Math.min(Math.max(ratio, 0), BAR_SCALE) / BAR_SCALE) * 100;
}

/** Plain-words fix for an infeasible result, based on what the user can change. */
export function suggestFix(reason: string, options: { locked: number; removed: number; onlyVerified: boolean }): string {
  const text = reason.toLowerCase();
  const kind = text.includes("protein") ? "a protein" : text.includes("staple") ? "a staple" : "a food";
  const fixes: string[] = [];
  if (options.locked > 0) fixes.push(`unlock ${kind}`);
  if (options.removed > 0) fixes.push(`bring back ${kind === "a food" ? "a removed food" : `a removed ${kind.slice(2)}`}`);
  if (options.onlyVerified) fixes.push("allow estimated foods");
  if (fixes.length === 0) return "Try widening your targets.";
  const sentence = fixes.length === 1 ? fixes[0]! : `${fixes.slice(0, -1).join(", ")} or ${fixes[fixes.length - 1]}`;
  return `${sentence.charAt(0).toUpperCase()}${sentence.slice(1)}.`;
}
