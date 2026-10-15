import { useEffect, useRef } from "react";
import { DayTargetsProvider } from "./dayTargets.tsx";
import { useHashRoute, type Route } from "./router.ts";
import EatOutScreen from "./screens/EatOutScreen.tsx";
import PlanScreen from "./screens/PlanScreen.tsx";
import SavedScreen from "./screens/SavedScreen.tsx";
import "./App.css";

const LINKS: { route: Route; label: string }[] = [
  { route: "plan", label: "Plan my day" },
  { route: "eat-out", label: "Eat out" },
  { route: "saved", label: "Saved plans" },
];

export default function App() {
  const route = useHashRoute();
  const firstRender = useRef(true);

  // After navigating (not on first load), move focus to the new screen's heading
  useEffect(() => {
    if (firstRender.current) {
      firstRender.current = false;
      return;
    }
    document.getElementById(`screen-${route}`)?.focus();
  }, [route]);

  return (
    <DayTargetsProvider>
      <div className="page">
        <header className="page-header">
          <h1 className="page-title">Nutrition engine</h1>
          <nav className="nav" aria-label="Main">
            {LINKS.map((link) => (
              <a key={link.route} href={`#/${link.route}`} aria-current={route === link.route ? "page" : undefined}>
                {link.label}
              </a>
            ))}
          </nav>
        </header>

        {/* Every screen stays mounted so its state survives navigation; inactive ones are hidden */}
        <main>
          <div hidden={route !== "plan"}>
            <PlanScreen />
          </div>
          <div hidden={route !== "eat-out"}>
            <EatOutScreen />
          </div>
          <div hidden={route !== "saved"}>
            <SavedScreen active={route === "saved"} />
          </div>
        </main>
      </div>
    </DayTargetsProvider>
  );
}
