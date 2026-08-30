import streamlit as st
import solver
import calculator
import os
import psycopg2
from dotenv import load_dotenv

load_dotenv()

# 1. SETUP - Must be the first Streamlit command
st.set_page_config(page_title="Nutrition Engine", layout="wide")

# 🚨 DIRECT DATABASE TEST TO EXPOSE THE REAL ERROR 🚨
try:
    conn = psycopg2.connect(
        host=os.getenv("DB_HOST", "localhost"),
        port=os.getenv("DB_PORT", 5432),
        database=os.getenv("DB_NAME", "nutrition_db"),
        user=os.getenv("DB_USER"),
        password=os.getenv("DB_PASSWORD", "")
    )
    conn.close()
except Exception as e:
    st.error(f"🚨 REAL DATABASE ERROR: {e}")
    st.warning("If the error says 'FATAL: role \"None\" does not exist', Python is not finding your .env file.")
    st.stop() # Stops the rest of the app from running so you can read the error

# 2. STATE MANAGEMENT - Initialize all four macro targets
if 'target_cal'   not in st.session_state: st.session_state.target_cal   = 2800
if 'target_prot'  not in st.session_state: st.session_state.target_prot  = 170
if 'target_carbs' not in st.session_state: st.session_state.target_carbs = 390
if 'target_fat'   not in st.session_state: st.session_state.target_fat   = 68

st.title("🍎 Nutrition Engine Optimizer")
st.markdown("Automated meal planning using Heuristic Optimization & PostgreSQL.")

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
                winner = solver.run_heuristic_solver(
                    foods, target_cal, target_prot, target_carbs, target_fat
                )
                
                if winner:
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
                else:
                    st.error("No valid meal plan found with current constraints.")
            else:
                st.error("Database connected successfully, but returned empty data.")

# ---------------------------------------------------------
# TAB 2: EATING OUT (HYBRID)
# ---------------------------------------------------------
with tab_restaurant:
    st.subheader("Restaurant Hybrid Plan")
    st.caption("Select where you want to eat out. The engine incorporates that restaurant meal and fills the rest of your day with home cooking.")
    
    col_rest, col_slot = st.columns(2)
    with col_rest:
        restaurant = st.selectbox("Select Restaurant", ["Chipotle", "CAVA"])
    with col_slot:
        out_meal_slot = st.selectbox("Which meal are you eating out?", ["Lunch", "Dinner"])
        
    if st.button("Generate Restaurant Hybrid Plan"):
        with st.spinner(f"Building plan around {restaurant}..."):
            foods = solver.load_food_data(mode="eating_out", restaurant=restaurant)
            
            if foods:
                winner = solver.run_heuristic_solver(
                    foods, target_cal, target_prot, target_carbs, target_fat,
                    restaurant=restaurant, 
                    restaurant_meal=out_meal_slot
                )
                
                if winner:
                    col1, col2 = st.columns(2)
                    with col1:
                        st.subheader(f"Meal Plan (Includes {restaurant})")
                        current_meal = None
                        for item in winner['items']:
                            if item['meal'] != current_meal:
                                current_meal = item['meal']
                                st.markdown(f"**🍽️ {current_meal}**")
                            
                            # Highlight restaurant items
                            is_restaurant_item = restaurant.lower() in item['name'].lower()
                            tag = f" `[{restaurant.upper()}]`" if is_restaurant_item else f" `[{item['category'].upper()}]`"
                            st.write(f"  • **{item['servings']}x** {item['name']}{tag}")
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
                else:
                    st.error("No valid meal plan found with current constraints.")
            else:
                st.error("Database connected successfully, but returned empty data.")