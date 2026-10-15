import { createContext, useContext, useState, type ReactNode } from "react";
import type { DailyTargets } from "./api.ts";

export const DEFAULT_DAY_TARGETS: DailyTargets = { calories: 2800, protein: 170, carbs: 390, fat: 68 };

interface DayTargetsValue {
  /** The planner's current day targets (its last plan's, else what the targets panel holds) */
  dayTargets: DailyTargets;
  setDayTargets: (targets: DailyTargets) => void;
}

const DayTargetsContext = createContext<DayTargetsValue | null>(null);

export function DayTargetsProvider({ children }: { children: ReactNode }) {
  const [dayTargets, setDayTargets] = useState<DailyTargets>(DEFAULT_DAY_TARGETS);
  return <DayTargetsContext.Provider value={{ dayTargets, setDayTargets }}>{children}</DayTargetsContext.Provider>;
}

export function useDayTargets(): DayTargetsValue {
  const value = useContext(DayTargetsContext);
  if (!value) throw new Error("useDayTargets must be used inside DayTargetsProvider");
  return value;
}
