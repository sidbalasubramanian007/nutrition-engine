import { useEffect, useState } from "react";

export const ROUTES = ["plan", "eat-out", "saved"] as const;
export type Route = (typeof ROUTES)[number];

function parse(hash: string): Route {
  const path = hash.replace(/^#\/?/, "");
  return (ROUTES as readonly string[]).includes(path) ? (path as Route) : "plan";
}

/** The current hash route (#/plan, #/eat-out, #/saved); refresh and the back button just work. */
export function useHashRoute(): Route {
  const [route, setRoute] = useState<Route>(() => parse(window.location.hash));
  useEffect(() => {
    if (!window.location.hash) window.history.replaceState(null, "", "#/plan");
    const onChange = () => setRoute(parse(window.location.hash));
    window.addEventListener("hashchange", onChange);
    return () => window.removeEventListener("hashchange", onChange);
  }, []);
  return route;
}
