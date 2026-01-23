import pandas as pd
import matplotlib.pyplot as plt

# ---------------------------------------------------------
# 1. Load and filter KS2
# ---------------------------------------------------------
df = pd.read_csv("school-pupils-and-their-characteristics_2024-25/data/spc_class_size.csv")
ks2 = df[df["classtype"] == "KS2"].copy()

# Clean numeric
ks2["average_class_size"] = pd.to_numeric(ks2["average_class_size"], errors="coerce")
ks2 = ks2.dropna(subset=["average_class_size"])

# ---------------------------------------------------------
# 2. Aggregate KS2 class sizes by area + year
# ---------------------------------------------------------
agg = (
    ks2.groupby(["time_period", "la_name"])["average_class_size"]
    .mean()
    .reset_index()
)

# Sort years in proper sequence
agg = agg.sort_values(["la_name", "time_period"])

# ---------------------------------------------------------
# 3. Compute year-to-year change
# ---------------------------------------------------------
agg["prev_avg"] = agg.groupby("la_name")["average_class_size"].shift(1)
agg["change"] = agg["average_class_size"] - agg["prev_avg"]

# Decline indicator
agg["decline"] = agg["change"] < 0

# ---------------------------------------------------------
# 4. Table: All years where class sizes declined
# ---------------------------------------------------------
declines = agg[agg["decline"] == True].copy()
print("\n===== YEARS WITH KS2 CLASS SIZE DECLINE =====")
print(declines[["la_name", "time_period", "average_class_size", "change"]])

# ---------------------------------------------------------
# 5. Biggest declines (per area + overall)
# ---------------------------------------------------------
biggest_declines = (
    declines.sort_values("change")  # most negative first
    .groupby("la_name")
    .first()
)
overall_biggest_decline = declines.sort_values("change").head(10)

print("\n===== BIGGEST DECLINE PER AREA =====")
print(biggest_declines[["time_period", "change"]])

print("\n===== TOP 10 BIGGEST DECLINES OVERALL =====")
print(overall_biggest_decline[["la_name", "time_period", "change"]])

# ---------------------------------------------------------
# 6. PLOT: highlight declines
# ---------------------------------------------------------

# Pivot for basic line plot
pivot = agg.pivot(index="time_period", columns="la_name", values="average_class_size")

plt.figure(figsize=(16, 9))
plt.plot(pivot, alpha=0.4)  # Basic trend lines

# Overlay red dots for declines
for _, row in declines.iterrows():
    plt.scatter(
        row["time_period"],
        row["average_class_size"],
        color="red",
        s=40,
        zorder=5
    )

plt.title("KS2 Average Class Size Over Time — Declines Highlighted")
plt.xlabel("Academic Year")
plt.ylabel("Average KS2 Class Size")
plt.xticks(rotation=45)
plt.grid(True)
plt.tight_layout()
plt.savefig('random_graph.png')
plt.show()
