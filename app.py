import streamlit as st
import solver
import calculator

# 1. SETUP - Must be the first Streamlit command
st.set_page_config(page_title="Nutrition Engine", layout="wide")

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

# 5. MAIN CONTENT - The Solver
if st.button("Generate Optimal Plan"):
    with st.spinner("Calculating optimal meal plan..."):
        food_db = solver.load_food_data()
        if food_db:
            winner = solver.run_heuristic_solver(
                food_db,
                target_calories=target_cal,
                target_protein=target_prot,
                target_carbs=target_carbs,
                target_fat=target_fat,
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
            st.error("Database connection failed. Check your PostgreSQL instance!")
