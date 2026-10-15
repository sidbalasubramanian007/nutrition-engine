/**
 * Typed client for the FastAPI backend in api/. Types mirror api/models.py.
 * Base URL comes from VITE_API_URL (default http://127.0.0.1:8000).
 */

export const API_URL = (import.meta.env.VITE_API_URL ?? "http://127.0.0.1:8000").replace(/\/+$/, "");

// --- shared literals ---

/** "Grocery" or a restaurant; restaurants come from the data (see getFoods). */
export type Location = string;
/** A restaurant location from getFoods, e.g. "Chipotle". Unknown ones are a 422. */
export type Restaurant = string;
export type Status = "optimal" | "feasible" | "infeasible";
export type DailyMeal = "Breakfast" | "Lunch" | "Dinner" | "Snack";
export type MealName = DailyMeal | "Order";
export type Gender = "Male" | "Female";
export type Activity = "Sedentary" | "Lightly Active" | "Moderately Active" | "Very Active";
export type Goal = "Maintenance" | "Bulking" | "Cutting";

// --- targets ---

/** A full day's targets. Server limits: calories 1000-6000, protein 0-500, carbs 0-1000, fat 0-400. */
export interface DailyTargets {
  calories: number;
  protein: number;
  carbs: number;
  fat: number;
}

/** One restaurant meal's targets. Server limits: calories 100-3000, protein 0-300, carbs 0-500, fat 0-200. */
export type MealTargets = DailyTargets;

/** Targets as stored with a saved plan (no range checks). */
export type Targets = DailyTargets;

export interface TargetsRequest {
  /** 13-100 */
  age: number;
  /** 70-700 */
  weight_lbs: number;
  /** 3-8 */
  height_ft: number;
  /** 0 to under 12 */
  height_in: number;
  gender: Gender;
  activity: Activity;
  goal: Goal;
}

export interface TargetsResponse {
  calories: number;
  protein: number;
  carbs: number;
  fat: number;
}

// --- foods ---

export interface Macros {
  calories: number;
  protein: number;
  carbs: number;
  fat: number;
  fiber: number;
}

/** One product, with macros per serving. */
export interface Food extends Macros {
  name: string;
  location: string;
  category: string;
  max_servings: number;
  meal_slots: string[];
  component_type: string | null;
  source: string;
}

export interface FoodsQuery {
  location?: Location;
  exclude_estimated?: boolean;
}

// --- plans and orders ---

export interface PlanItem {
  name: string;
  servings: number;
  category: string;
  /** Totals for these servings */
  macros: Macros;
}

export interface MealGroup {
  name: MealName;
  items: PlanItem[];
}

/** A daily plan (Breakfast/Lunch/Dinner/Snack) or a restaurant order (one "Order" group). */
export interface Plan {
  status: Status;
  meals: MealGroup[];
  macros: Macros | null;
  penalty: number | null;
  solve_time: number;
  solver: string;
  /** Why no plan was found (e.g. which lock conflicts), when infeasible */
  message: string | null;
}

export interface LockedItem {
  name: string;
  meal: DailyMeal;
  /** 1-3; snacks allow 1, main meals up to min(max_servings, 3) */
  servings: number;
}

export interface PlanRequest {
  targets: DailyTargets;
  exclude_estimated?: boolean;
  /** Seconds, above 0 and at most 5 (default 1) */
  time_limit?: number;
  /** Up to 8 */
  locked?: LockedItem[];
  /** Food names that must not appear (up to 200) */
  excluded?: string[];
}

export interface RestaurantRequest {
  restaurant: Restaurant;
  targets: MealTargets;
}

export interface SavePlanRequest {
  /** A daily plan as returned by optimizePlan, with status "optimal" or "feasible" */
  plan: Plan;
  targets: DailyTargets;
}

export interface SavePlanResponse {
  id: number;
}

export interface SavedPlanSummary {
  id: number;
  /** ISO 8601 timestamp */
  created_at: string;
  targets: Targets;
  /** Achieved, from the foods' current macros */
  macros: Macros;
  penalty: number;
  status: Status;
  solver: string;
  item_count: number;
}

export interface SavedPlan {
  id: number;
  /** ISO 8601 timestamp */
  created_at: string;
  targets: Targets;
  meals: MealGroup[];
  /** Achieved, from the foods' current macros */
  macros: Macros;
  penalty: number;
  status: Status;
  solver: string;
}

export interface Health {
  status: "ok";
  db: boolean;
}

// --- errors ---

/** One entry of FastAPI's 422 validation detail. */
export interface ValidationIssue {
  loc: (string | number)[];
  msg: string;
  type: string;
}

/** A non-2xx response, or a network failure (status 0). */
export class ApiError extends Error {
  readonly status: number;
  readonly detail: string | ValidationIssue[] | null;

  constructor(status: number, detail: string | ValidationIssue[] | null, message: string) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.detail = detail;
  }
}

function describe(detail: string | ValidationIssue[] | null, status: number): string {
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail) && detail.length > 0) {
    return detail.map((issue) => `${issue.loc.filter((part) => part !== "body").join(".")}: ${issue.msg}`).join("; ");
  }
  return `Request failed (HTTP ${status})`;
}

// --- requests ---

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`${API_URL}${path}`, {
      ...init,
      headers: { Accept: "application/json", ...(init?.body ? { "Content-Type": "application/json" } : {}), ...init?.headers },
    });
  } catch (error) {
    if (error instanceof DOMException && error.name === "AbortError") throw error;
    throw new ApiError(0, null, `Can't reach the API at ${API_URL}`);
  }

  if (!response.ok) {
    let detail: string | ValidationIssue[] | null = null;
    try {
      const body: unknown = await response.json();
      if (body && typeof body === "object" && "detail" in body) {
        detail = (body as { detail: string | ValidationIssue[] }).detail;
      }
    } catch {
      // Non-JSON error body
    }
    throw new ApiError(response.status, detail, describe(detail, response.status));
  }
  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}

function post<T>(path: string, body: unknown, signal?: AbortSignal): Promise<T> {
  return request<T>(path, { method: "POST", body: JSON.stringify(body), signal });
}

/** GET /api/health */
export function getHealth(signal?: AbortSignal): Promise<Health> {
  return request<Health>("/api/health", { signal });
}

/** GET /api/foods */
export function getFoods(query: FoodsQuery = {}, signal?: AbortSignal): Promise<Food[]> {
  const params = new URLSearchParams();
  if (query.location) params.set("location", query.location);
  if (query.exclude_estimated !== undefined) params.set("exclude_estimated", String(query.exclude_estimated));
  const search = params.toString();
  return request<Food[]>(`/api/foods${search ? `?${search}` : ""}`, { signal });
}

/** POST /api/targets/calculate */
export function calculateTargets(body: TargetsRequest, signal?: AbortSignal): Promise<TargetsResponse> {
  return post<TargetsResponse>("/api/targets/calculate", body, signal);
}

/** POST /api/plans/optimize. An infeasible plan resolves normally with status "infeasible". */
export function optimizePlan(body: PlanRequest, signal?: AbortSignal): Promise<Plan> {
  return post<Plan>("/api/plans/optimize", body, signal);
}

/** POST /api/restaurant/optimize. Resolves to a Plan with one "Order" meal group. */
export function optimizeRestaurantOrder(body: RestaurantRequest, signal?: AbortSignal): Promise<Plan> {
  return post<Plan>("/api/restaurant/optimize", body, signal);
}

/** POST /api/plans/save */
export function savePlan(body: SavePlanRequest, signal?: AbortSignal): Promise<SavePlanResponse> {
  return post<SavePlanResponse>("/api/plans/save", body, signal);
}

/** GET /api/plans (newest first; limit 1-100, default 20) */
export function listPlans(limit = 20, signal?: AbortSignal): Promise<SavedPlanSummary[]> {
  return request<SavedPlanSummary[]>(`/api/plans?limit=${encodeURIComponent(limit)}`, { signal });
}

/** GET /api/plans/{id}. Rejects with ApiError status 404 if the plan doesn't exist. */
export function getPlan(id: number, signal?: AbortSignal): Promise<SavedPlan> {
  return request<SavedPlan>(`/api/plans/${encodeURIComponent(id)}`, { signal });
}

/** DELETE /api/plans/{id}. Rejects with ApiError status 404 if the plan doesn't exist. */
export function deletePlan(id: number, signal?: AbortSignal): Promise<void> {
  return request<void>(`/api/plans/${encodeURIComponent(id)}`, { method: "DELETE", signal });
}
