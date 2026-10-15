"""Pydantic request and response models. Requests reject unknown fields, so typos are a 422."""
from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

Status = Literal["optimal", "feasible", "infeasible"]
MealName = Literal["Breakfast", "Lunch", "Dinner", "Snack", "Order"]
DAILY_MEALS = ("Breakfast", "Lunch", "Dinner", "Snack")


class Request(BaseModel):
    model_config = ConfigDict(extra="forbid")


# --- targets ---

class DailyTargets(Request):
    """A full day's macro targets."""
    calories: float = Field(ge=1000, le=6000)
    protein: float = Field(ge=0, le=500)
    carbs: float = Field(ge=0, le=1000)
    fat: float = Field(ge=0, le=400)


class Targets(BaseModel):
    """Targets as stored with a saved plan (responses only, so no range checks)."""
    calories: float
    protein: float
    carbs: float
    fat: float


class MealTargets(Request):
    """Macro targets for one restaurant meal."""
    calories: float = Field(ge=100, le=3000)
    protein: float = Field(ge=0, le=300)
    carbs: float = Field(ge=0, le=500)
    fat: float = Field(ge=0, le=200)


class TargetsRequest(Request):
    age: int = Field(ge=13, le=100)
    weight_lbs: float = Field(ge=70, le=700)
    height_ft: int = Field(ge=3, le=8)
    height_in: float = Field(ge=0, lt=12)
    gender: Literal["Male", "Female"]
    activity: Literal["Sedentary", "Lightly Active", "Moderately Active", "Very Active"]
    goal: Literal["Maintenance", "Bulking", "Cutting"]


class TargetsResponse(BaseModel):
    calories: int
    protein: int
    carbs: int
    fat: int


# --- foods ---

class Macros(BaseModel):
    calories: float
    protein: float
    carbs: float
    fat: float
    fiber: float


class Food(Macros):
    """One product, with macros per serving."""
    name: str
    location: str
    category: str
    max_servings: int
    meal_slots: list[str]
    component_type: Optional[str] = None
    source: str


# --- plans and orders ---

class PlanItem(BaseModel):
    name: str
    servings: int = Field(ge=1)
    category: str
    macros: Macros = Field(description="Totals for these servings")


class MealGroup(BaseModel):
    name: MealName
    items: list[PlanItem]


class Plan(BaseModel):
    """A daily plan (Breakfast/Lunch/Dinner/Snack) or a restaurant order (one "Order" group)."""
    status: Status
    meals: list[MealGroup]
    macros: Optional[Macros] = None
    penalty: Optional[float] = None
    solve_time: float
    solver: str
    message: Optional[str] = Field(None, description="Why no plan was found (e.g. which lock conflicts), when infeasible")


class LockedItem(Request):
    """A food that must appear in a meal at exactly this many servings."""
    name: str = Field(min_length=1)
    meal: Literal["Breakfast", "Lunch", "Dinner", "Snack"]
    servings: int = Field(ge=1, le=3, description="Snacks allow 1; main meals up to min(max_servings, 3)")


class PlanRequest(Request):
    targets: DailyTargets
    exclude_estimated: bool = False
    time_limit: float = Field(1, gt=0, le=5)
    locked: list[LockedItem] = Field(default_factory=list, max_length=8)
    excluded: list[str] = Field(default_factory=list, max_length=200, description="Food names that must not appear")


class RestaurantRequest(Request):
    restaurant: str = Field(min_length=1, description="A restaurant location from /api/foods, e.g. Chipotle")
    targets: MealTargets


class SavePlanRequest(Request):
    plan: Plan
    targets: DailyTargets

    @field_validator("plan")
    @classmethod
    def savable(cls, plan):
        if plan.status == "infeasible" or not plan.meals:
            raise ValueError("only plans with items (status 'optimal' or 'feasible') can be saved")
        if any(meal.name not in DAILY_MEALS for meal in plan.meals):
            raise ValueError("only daily plans can be saved (restaurant orders can't)")
        return plan


class SavePlanResponse(BaseModel):
    id: int


class SavedPlanSummary(BaseModel):
    id: int
    created_at: datetime
    targets: Targets
    macros: Macros = Field(description="Achieved, from the foods' current macros")
    penalty: float
    status: Status
    solver: str
    item_count: int


class SavedPlan(BaseModel):
    id: int
    created_at: datetime
    targets: Targets
    meals: list[MealGroup]
    macros: Macros = Field(description="Achieved, from the foods' current macros")
    penalty: float
    status: Status
    solver: str


class Health(BaseModel):
    status: Literal["ok"]
    db: bool
