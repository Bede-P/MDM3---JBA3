import pandas as pd
import numpy as np

from sklearn.preprocessing import StandardScaler
from sklearn.impute import SimpleImputer

import umap
import matplotlib.pyplot as plt

# --------------------------------------------------
# 1. Load data
# --------------------------------------------------
df = pd.read_excel("Master Data.xlsx")

# --------------------------------------------------
# 2. Select numeric columns only
#    (UMAP works on numbers)
# --------------------------------------------------
numeric_df = df.select_dtypes(include=[np.number])

# --------------------------------------------------
# 3. Handle missing values
#    (median is robust for skewed data)
# --------------------------------------------------
imputer = SimpleImputer(strategy="median")
X_imputed = imputer.fit_transform(numeric_df)

# --------------------------------------------------
# 4. Scale features
#    (critical for distance-based methods)
# --------------------------------------------------
scaler = StandardScaler()
X_scaled = scaler.fit_transform(X_imputed)

# --------------------------------------------------
# 5. Fit UMAP
# --------------------------------------------------
umap_model = umap.UMAP(
    n_neighbors=15,      # local vs global structure
    min_dist=0.1,        # cluster tightness
    n_components=2,      # 2D visualisation
    random_state=42
)

embedding = umap_model.fit_transform(X_scaled)

# --------------------------------------------------
# 6. Plot
# --------------------------------------------------
plt.figure(figsize=(10, 7))
plt.scatter(
    embedding[:, 0],
    embedding[:, 1],
    s=20,
    alpha=0.7
)

plt.title("UMAP projection of school & catchment data")
plt.xlabel("UMAP 1")
plt.ylabel("UMAP 2")
plt.show()
