import pandas as pd, glob

files = sorted(glob.glob('mass_case_description_*.csv')) + sorted(glob.glob('calc_case_description_*.csv'))
print('found files:', files)
print()

for f in files:
    df = pd.read_csv(f)
    print('=====', f, 'rows=', len(df))
    print('columns:', list(df.columns))
    for col in df.columns:
        lc = col.lower().strip()
        if lc == 'assessment':
            print('  [Q1] assessment 분포:')
            print(df[col].value_counts().sort_index().to_string())
        if lc == 'pathology':
            print('  [Q2] pathology 분포:')
            print(df[col].value_counts().to_string())
        if 'shape' in lc or 'margin' in lc or 'distribution' in lc:
            print('  [Q3/Q4]', col, '고유값:')
            print(df[col].value_counts(dropna=False).to_string())
        if lc == 'calc type':
            print('  [Q3/Q4]', col, '고유값:')
            print(df[col].value_counts(dropna=False).to_string())
        if 'view' in lc or 'exam' in lc:
            print('  [Q5 후보]', col, '고유값:', sorted(df[col].dropna().unique().tolist())[:10])
    print()
