import streamlit as st
import solver
import calculator
import optimizer
import db
from dotenv import load_dotenv

load_dotenv()

# 1. SETUP - Must be the first Streamlit command
st.set_page_config(page_title="Nutrition Engine", layout="wide")

# Fail fast with setup instructions if the database is unreachable
try:
    db.get_connection().close()
except Exception as e:
    st.error(
        f"Could not connect to the database ({e}). Make sure PostgreSQL is running, "
        "then set DATABASE_URL, or DB_HOST/DB_PORT/DB_NAME/DB_USER/DB_PASSWORD, in a .env file "
        "in the repo root (see .env.example) and restart the app."
    )
    st.stop()

# 2. STATE MANAGEMENT - Initialize all four macro targets
if 'target_cal'   not in st.session_state: st.session_state.target_cal   = 2800
if 'target_prot'  not in st.session_state: st.session_state.target_prot  = 170
if 'target_carbs' not in st.session_state: st.session_state.target_carbs = 390
if 'target_fat'   not in st.session_state: st.session_state.target_fat   = 68

st.title("🍎 Nutrition Engine Optimizer")
st.markdown("Automated meal planning using Mixed-Integer Optimization & PostgreSQL.")

# 3. SIDEBAR - Calculator
st.sidebar.header("TDEE Calculator")
age       = st.sidebar.number_input("Age",           value=18)
weight    = st.sidebar.number_input("Weight (lbs)",  value=170)
height_ft = st.sidebar.number_input("Height (ft)",   value=6)
height_in = st.sidebar.number_input("Height (in)",   value=1)
gender    = st.sidebar.selectbox("Gender", ["Male", "Female"])
activity  = st.sidebar.selectbox("Activity Level", ["Sedentary", "Lightly Active", "Moderately Active", "Very Active"])
goal      = st.sidebar.selectbox("Goal", ["Maintenance", "Bulking", "Cutting"])

if st.sidebar.button("Calculate & Apply Targets"):
    cals       = calculator.calculate_tdee(weight, height_ft, height_in, age, gender, activity, goal)
    prot       = calculator.estimate_protein(weight, goal)
    fat, carbs = calculator.estimate_fat_and_carbs(cals, prot)
    st.session_state.target_cal   = cals
    st.session_state.target_prot  = prot
    st.session_state.target_fat   = fat
    st.session_state.target_carbs = carbs
    st.sidebar.success("Targets Updated!")

# 4. SIDEBAR - Optimization Targets (all four macros)
st.sidebar.header("Optimization Targets")
target_cal   = st.sidebar.slider("Target Calories",    1500, 4000, st.session_state.target_cal)
target_prot  = st.sidebar.slider("Target Protein (g)",   50,  250, st.session_state.target_prot)
target_carbs = st.sidebar.slider("Target Carbs (g)",     50,  600, st.session_state.target_carbs)
target_fat   = st.sidebar.slider("Target Fat (g)",       20,  150, st.session_state.target_fat)


# Solver time budget for home plans and restaurant orders; the best result found so far is
# returned if not yet proven optimal
HOME_PLAN_TIME_LIMIT = 1
RESTAURANT_ORDER_TIME_LIMIT = 1

def show_solver_status(result, time_limit):
    """Status line under a macro breakdown for an optimal or feasible optimizer result."""
    if result['status'] == "optimal":
        st.caption(f"Proven optimal · solved in {result['solve_time']:.2f}s")
    else:
        st.caption(f"Best plan found in {time_limit}s (not yet proven optimal)")

# 5. MAIN CONTENT - TWO DISTINCT MODES
tab_grocery, tab_restaurant = st.tabs(["🍳 Home Cooking Plan", "🥗 Eating Out Plan"])

# ---------------------------------------------------------
# TAB 1: HOME COOKING (PURE GROCERY)
# ---------------------------------------------------------
with tab_grocery:
    st.subheader("Home-Cooked Daily Meal Prep")
    st.caption("Generates a structured daily plan built strictly from standard grocery ingredients.")
    
    if st.button("Generate Home Meal Plan"):
        with st.spinner("Optimizing grocery meal plan..."):
            foods = solver.load_food_data(mode="grocery")
            
            if foods:
                winner = optimizer.optimize_meal_plan(
                    foods, target_cal, target_prot, target_carbs, target_fat,
                    time_limit=HOME_PLAN_TIME_LIMIT,
                )
                
                if winner['status'] != "infeasible":
                    col1, col2 = st.columns(2)
                    with col1:
                        st.subheader("Meal Plan")
                        current_meal = None
                        for item in winner['items']:
                            if item['meal'] != current_meal:
                                current_meal = item['meal']
                                st.markdown(f"**🍽️ {current_meal}**")
                            st.write(f"  • **{item['servings']}x** {item['name']} `[{item['category'].upper()}]`")

                    with col2:
                        st.subheader("Macro Breakdown")
                        st.metric("Calories", f"{winner['macros']['calories']} kcal",
                                  delta=f"{winner['macros']['calories'] - target_cal:+} vs target")
                        st.metric("Protein",  f"{winner['macros']['protein']}g",
                                  delta=f"{winner['macros']['protein'] - target_prot:+.0f}g vs target")
                        st.metric("Carbs",    f"{winner['macros']['carbs']}g",
                                  delta=f"{winner['macros']['carbs'] - target_carbs:+.0f}g vs target")
                        st.metric("Fat",      f"{winner['macros']['fat']}g",
                                  delta=f"{winner['macros']['fat'] - target_fat:+.0f}g vs target")
                        st.metric("Fiber",    f"{winner['macros']['fiber']}g")
                        show_solver_status(winner, HOME_PLAN_TIME_LIMIT)
                else:
                    st.error(
                        "No meal plan fits the meal structure (a staple and a protein at breakfast, lunch "
                        "and dinner, plus a snack, with fiber under 35g) using the foods currently loaded. "
                        "Try loading more foods with `python scripts/setup_db.py --with-seeds`, "
                        "or widen your targets."
                    )
            else:
                st.error("Database connected successfully, but returned empty data.")

# ---------------------------------------------------------
# TAB 2: EATING OUT (HYBRID)
# ---------------------------------------------------------
with tab_restaurant:
    st.subheader("Restaurant Hub")
    
    restaurant = st.selectbox("Select Restaurant", ["Chipotle", "CAVA"], key="rest_select")
    
    # Load the foods for the selected restaurant
    foods = solver.load_food_data(mode="eating_out", restaurant=restaurant)
    rest_foods = [f for f in foods if f.get('location') == restaurant] if foods else []
    
    if not rest_foods:
        st.error(f"No menu items found for {restaurant} in the database.")
    else:
        # Toggle between Calculator and Optimizer
        mode = st.radio("What do you want to do?", ["Calculate My Order", "Auto-Build Perfect Order"], horizontal=True)
        st.markdown("---")
        
        if mode == "Calculate My Order":
            st.caption(f"Select your usual {restaurant} ingredients to see the exact macro breakdown.")
            
            food_names = [f['name'] for f in rest_foods]
            selected_item_names = st.multiselect("What's in your order?", food_names)
            
            if selected_item_names:
                st.markdown("**Adjust Servings (e.g., Double Meat)**")
                order_totals = {"calories": 0, "protein": 0.0, "carbs": 0.0, "fat": 0.0, "fiber": 0.0}
                
                col_items, col_macros = st.columns([1.5, 1])
                
                with col_items:
                    for name in selected_item_names:
                        food = next(f for f in rest_foods if f['name'] == name)
                        servings = st.number_input(f"{name}", min_value=0.5, max_value=5.0, value=1.0, step=0.5, key=f"serv_{name}")
                        
                        order_totals["calories"] += food["calories"] * servings
                        order_totals["protein"]  += food["protein"]  * servings
                        order_totals["carbs"]    += food["carbs"]    * servings
                        order_totals["fat"]      += food["fat"]      * servings
                        order_totals["fiber"]    += food["fiber"]    * servings
                        
                with col_macros:
                    st.subheader("Order Macros")
                    st.metric("Calories", f"{order_totals['calories']:.0f} kcal")
                    st.metric("Protein", f"{order_totals['protein']:.0f}g")
                    st.metric("Carbs", f"{order_totals['carbs']:.0f}g")
                    st.metric("Fat", f"{order_totals['fat']:.0f}g")
                    st.metric("Fiber", f"{order_totals['fiber']:.1f}g")

        else:
            # The MILP Auto-Builder
            st.caption("Input the macros you have left for the day, and the engine will hack the menu to build the perfect order.")
            
            colA, colB, colC, colD = st.columns(4)
            meal_cal  = colA.number_input("Target Cals", value=int(st.session_state.target_cal / 3), step=50)
            meal_prot = colB.number_input("Target Protein",  value=int(st.session_state.target_prot / 3), step=5)
            meal_carb = colC.number_input("Target Carbs",    value=int(st.session_state.target_carbs / 3), step=5)
            meal_fat  = colD.number_input("Target Fat",      value=int(st.session_state.target_fat / 3), step=5)
            
            if st.button("Hack My Menu"):
                with st.spinner(f"Optimizing {restaurant} menu..."):
                    winner = optimizer.optimize_restaurant_order(
                        rest_foods, meal_cal, meal_prot, meal_carb, meal_fat,
                        time_limit=RESTAURANT_ORDER_TIME_LIMIT,
                    )
                    
                    if winner['status'] != "infeasible":
                        col1, col2 = st.columns(2)
                        with col1:
                            st.subheader("Your Custom Order")
                            for item in winner['items']:
                                st.write(f"  • **{item['servings']}x** {item['name']}")
                        with col2:
                            st.subheader("Order Macros")
                            st.metric("Calories", f"{winner['macros']['calories']} kcal", 
                                      delta=f"{winner['macros']['calories'] - meal_cal:+} vs target")
                            st.metric("Protein", f"{winner['macros']['protein']}g", 
                                      delta=f"{winner['macros']['protein'] - meal_prot:+.0f}g vs target")
                            st.metric("Carbs", f"{winner['macros']['carbs']}g", 
                                      delta=f"{winner['macros']['carbs'] - meal_carb:+.0f}g vs target")
                            st.metric("Fat", f"{winner['macros']['fat']}g", 
                                      delta=f"{winner['macros']['fat'] - meal_fat:+.0f}g vs target")
                            show_solver_status(winner, RESTAURANT_ORDER_TIME_LIMIT)
                    else:
                        st.error(
                            f"No order fits the order structure (1-2 bases, 1-2 proteins, at most 1 beans, "
                            f"at most 4 toppings and sauces) with {restaurant}'s menu items. Make sure every "
                            f"{restaurant} item has a Component_Type, then reload with `python scripts/setup_db.py`."
                        )