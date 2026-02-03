import pandas as pd
import numpy as np
import cvxpy as cp
import matplotlib.pyplot as plt

# -----------------------------
# LOAD AND PREP DATA
# -----------------------------

df = pd.read_csv("school_flooding_data.csv")

# Define key variables
OUTCOME = "Attainment score"
TREATMENT = "Road flood days per year"  # or % road length flooded
UNIT = "School URN"
TIME = "Year"

# Identify treated unit
treated_school_urn = 107477  # Rawson Junior

# Define treatment year (first year flooding meaningfully occurs)
treatment_year = 2013

# -----------------------------
# SPLIT DATA
# -----------------------------

treated = df[df[UNIT] == treated_school_urn]
controls = df[df[UNIT] != treated_school_urn]

# Pivot to matrix form
Y = df.pivot(index=TIME, columns=UNIT, values=OUTCOME)

# Pre- and post-treatment periods
pre_period = Y.index < treatment_year
post_period = Y.index >= treatment_year

Y1_pre = Y.loc[pre_period, treated_school_urn].values
Y0_pre = Y.loc[pre_period, controls[UNIT].unique()].values

# -----------------------------
# SYNTHETIC CONTROL OPTIMISATION
# -----------------------------

n_controls = Y0_pre.shape[1]

# Weights must be non-negative and sum to 1
W = cp.Variable(n_controls)

objective = cp.Minimize(cp.sum_squares(Y1_pre - Y0_pre @ W))
constraints = [
    W >= 0,
    cp.sum(W) == 1
]

problem = cp.Problem(objective, constraints)
problem.solve()

weights = W.value

# -----------------------------
# CONSTRUCT SYNTHETIC SERIES
# -----------------------------

Y0_full = Y.loc[:, controls[UNIT].unique()].values
synthetic_attainment = Y0_full @ weights

# -----------------------------
# PLOT RESULTS
# -----------------------------

plt.figure(figsize=(10,6))
plt.plot(Y.index, Y[treated_school_urn], label="Observed (Flooded)", linewidth=2)
plt.plot(Y.index, synthetic_attainment, label="Synthetic (No Flooding)", linestyle="--")
plt.axvline(treatment_year, color="red", linestyle=":", label="Flooding onset")

plt.xlabel("Year")
plt.ylabel("Attainment score")
plt.title("Synthetic Control Estimate of Flooding Impact on Attainment")
plt.legend()
plt.tight_layout()
plt.show()

# -----------------------------
# TREATMENT EFFECT
# -----------------------------

treatment_effect = Y.loc[post_period, treated_school_urn].values - synthetic_attainment[post_period]

print("Estimated treatment effects (post-flood):")
for year, effect in zip(Y.index[post_period], treatment_effect):
    print(f"{year}: {effect:.2f}")
