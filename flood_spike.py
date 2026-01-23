import pandas as pd
import matplotlib.pyplot as plt

df = pd.read_csv('school-pupils-and-their-characteristics_2024-25/data/pupil-absence-in-schools-in-england_2024-25-autumn-and-spring-term/data/Absence_2term_nat_reg_la_termly.csv', low_memory=False)

# Local authority + Total phase only
la = df[(df['geographic_level'] == 'Local authority') &
        (df['education_phase'] == 'State-funded primary')].copy()
# la = df[(df['geographic_level'] == 'Local authority') &
#         (df['education_phase'] == 'Total')].copy()

# ---------------------------------------------------------
# Filter to Local Authorities containing "Lincolnshire"
# ---------------------------------------------------------
la = la[la['la_name'].str.contains('Lincolnshire', case=False, na=False)].copy()


# Term ordering
term_order = {'Autumn term': 1, 'Spring term': 2, 'Summer term': 3}
la = la[la['time_identifier'].isin(term_order)].copy()
la['term_rank'] = la['time_identifier'].map(term_order)
la['term_index'] = la['time_period'] * 10 + la['term_rank']

# ---------------------------------------------------------
# EXCLUDE nationally-disrupted terms (COVID-dominated)
# ---------------------------------------------------------
exclude_terms = [
    (202021, 'Summer term'),
    (202122, 'Autumn term'),
    (202122, 'Spring term'),
    (202122, 'Summer term')
]

mask = ~la[['time_period','time_identifier']].apply(tuple, axis=1).isin(exclude_terms)
la = la[mask].copy()


# Numeric overall absence
la['sess_overall_totalreasons_rate'] = pd.to_numeric(
    la['sess_overall_totalreasons_rate'], errors='coerce'
)

# Sort and compute term-on-term change per LA
la = la.sort_values(['la_name', 'term_index'])
la['prev_rate'] = la.groupby('la_name')['sess_overall_totalreasons_rate'].shift(1)
la['change_overall'] = la['sess_overall_totalreasons_rate'] - la['prev_rate']

# Define "spike" as top 10% of positive changes
threshold = la['change_overall'].quantile(0.9)
la['is_spike'] = la['change_overall'] > threshold

# # Count spikes and shares by term × region
# spike_summary = (la[la['is_spike']]
#     .groupby(['time_period','time_identifier','region_name'])
#     .agg(num_spikes=('la_name','nunique'))
#     .reset_index()
# )
#
# total_las = (la.groupby(['time_period','time_identifier','region_name'])
#              .agg(total_las=('la_name','nunique'))
#              .reset_index())
#
# spike_share = spike_summary.merge(total_las, on=['time_period','time_identifier','region_name'])
# spike_share['share_spiking'] = spike_share['num_spikes'] / spike_share['total_las']
# spike_share['term_label'] = spike_share['time_period'].astype(str) + ' ' + spike_share['time_identifier']
#
# # Pivot to term × region matrix
# heat = spike_share.pivot(index='term_label', columns='region_name', values='share_spiking').fillna(0)

# # ---------------------------------------------------------
# # Count spikes by term × Local Authority (NOT region)
# # ---------------------------------------------------------
# spike_summary = (la[la['is_spike']]
#     .groupby(['time_period','time_identifier','la_name'])
#     .agg(num_spikes=('la_name','count'))
#     .reset_index()
# )
#
# # Total records per term × LA
# total_las = (la
#     .groupby(['time_period','time_identifier','la_name'])
#     .agg(total_rows=('la_name','count'))
#     .reset_index()
# )
#
# spike_share = spike_summary.merge(
#     total_las,
#     on=['time_period','time_identifier','la_name'],
#     how='right'
# ).fillna({'num_spikes':0})
#
# spike_share['share_spiking'] = spike_share['num_spikes'] / spike_share['total_rows']
#
# spike_share['term_label'] = spike_share['time_period'].astype(str) + ' ' + spike_share['time_identifier']
#
# # ---------------------------------------------------------
# # Pivot: rows = term, columns = la_name
# # ---------------------------------------------------------
# heat = spike_share.pivot(index='term_label',
#                          columns='la_name',
#                          values='share_spiking').fillna(0)
#
#
#
# # Plot heatmap
# plt.figure(figsize=(10, 8))
# plt.imshow(heat, aspect='auto')
# plt.xticks(range(len(heat.columns)), heat.columns, rotation=45, ha='right')
# plt.yticks(range(len(heat.index)), heat.index)
# plt.colorbar(label='Share of LAs with spike in absence')
# plt.title('Geographic concentration of absence spikes by term and\nlocal authority in state-funded primary schools')
# plt.tight_layout()
# plt.show()

# ---------------------------------------------------------
# REBASE total absence rates for heatmap visibility
# ---------------------------------------------------------

# We assume la already:
# - filtered to State-funded primary
# - filtered to Lincolnshire LAs
# - excluded COVID-dominated terms
# - has term_index and is sorted

# Keep numeric overall absence
la['sess_overall_totalreasons_rate'] = pd.to_numeric(
    la['sess_overall_totalreasons_rate'], errors='coerce'
)

# Sort properly
la = la.sort_values(['la_name', 'term_index'])

# ---------------------------------------------------------
# Rebase per Local Authority
# (each LA starts at 0, future terms are relative change)
# ---------------------------------------------------------
la['baseline'] = la.groupby('la_name')['sess_overall_totalreasons_rate'].transform('first')
la['rebased_absence'] = la['sess_overall_totalreasons_rate'] - la['baseline']

# Label terms
la['term_label'] = la['time_period'].astype(str) + ' ' + la['time_identifier']

# ---------------------------------------------------------
# Pivot: rows = term, columns = la_name
# ---------------------------------------------------------
heat = la.pivot(index='term_label',
                columns='la_name',
                values='rebased_absence').fillna(0)

# ---------------------------------------------------------
# Plot rebased heatmap
# ---------------------------------------------------------


plt.figure(figsize=(10, 6))
plt.imshow(heat, aspect='auto')
plt.xticks(range(len(heat.columns)), heat.columns, rotation=45, ha='right')
plt.yticks(range(len(heat.index)), heat.index)
plt.colorbar(label='Change in total absence rate from baseline')
plt.title('Rebased total absence rates – Lincolnshire state-funded primary')
plt.tight_layout()
plt.savefig('delete.png')
plt.show()


# ---------------------------------------------------------
# Save spike share table to CSV
# ---------------------------------------------------------
# output_file = "lincolnshire_primary_absence_spikes.csv"
# spike_share.to_csv(output_file, index=False)
#
# print(f"Spike summary saved to: {output_file}")
