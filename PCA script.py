import pandas as pd
import numpy as np
from sklearn.preprocessing import StandardScaler
from sklearn.decomposition import PCA


# load dataset
df = pd.read_excel("Master Data.xlsx")

# Select only numerical columns
numeric_df = df.select_dtypes(include=[np.number])

# Replace missing values with column means
numeric_df = numeric_df.fillna(numeric_df.mean())

# Standardise data
scaler = StandardScaler()
scaled_data = scaler.fit_transform(numeric_df)

# PCA
pca = PCA()
pca_data = pca.fit_transform(scaled_data) # Variance can be examined

# Explained variance ratio
explained_variance = pca.explained_variance_ratio_

# Create a DataFrame of principal components
pca_df = pd.DataFrame(
    pca_data,
    columns=[f"PC{i+1}" for i in range(pca_data.shape[1])]
)

print("Explained variance ratio for each principal component:")
for i, var in enumerate(explained_variance):
    print(f"PC{i+1}: {var:.3f}")

# Save PCA results to Excel 
pca_df.to_excel("PCA_Output.xlsx", index=False)
