import pandas as pd
from pathlib import Path

RAW = Path.home() / "workspace/breast/data/cbis/raw"

for f in ["labels/labels_mass_train.csv", "labels/labels_mass_test.csv",
          "labels/labels_calc_train.csv", "labels/labels_calc_test.csv"]:
    df = pd.read_csv(f)
    total = len(df)
    hits = sum((RAW / p.strip()).exists() for p in df["image_path"])
    print(f, "->", hits, "/", total, "  (%.1f%%)" % (100 * hits / total))
