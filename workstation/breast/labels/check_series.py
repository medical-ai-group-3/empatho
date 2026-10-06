import pandas as pd
from pathlib import Path

RAW = Path.home() / "workspace/breast/data/cbis/raw"
existing = {p.name for p in RAW.iterdir() if p.is_dir()}
print("다운로드된 시리즈 디렉터리 수:", len(existing))

for f in ["labels/labels_mass_train.csv", "labels/labels_mass_test.csv",
          "labels/labels_calc_train.csv", "labels/labels_calc_test.csv"]:
    df = pd.read_csv(f)
    series_uid = df["image_path"].str.strip().str.split("/").str[-2]
    hit = series_uid.isin(existing)
    print(f, "->", hit.sum(), "/", len(df), "  (%.1f%%)" % (100 * hit.mean()))
