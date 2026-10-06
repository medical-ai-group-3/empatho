import torch, collections, pathlib, re
FILES = {
 "us":    "~/app/models/us/ckpt/us_lora_best.pt",
 "mri":   "~/app/models/mri/serving/ckpt/mri_lora_best.pt",
 "mammo": "~/app/models/mammo/training/ckpt/last_lora.pt",
}
for name, p in FILES.items():
    p = pathlib.Path(p).expanduser()
    if not p.exists():
        print(name, "없음", p); continue
    sd = torch.load(p, map_location="cpu")
    if isinstance(sd, dict) and not any(k.endswith("lora_B") for k in sd):
        for k in ("state_dict","model","weights"):
            if k in sd and isinstance(sd[k], dict): sd = sd[k]; break
    keys = [k for k in sd if k.endswith("lora_B")]
    print("==", name, "| lora_B 자리", len(keys), "| 파일", round(p.stat().st_size/2**20,1), "MB")
    # 부위별로 쪼갠다 (최상위 두 토막)
    reg = collections.Counter(".".join(k.split(".")[:2]) for k in keys)
    for r, c in reg.most_common(): print("     ", r, c)
    # 종류별
    kind = collections.Counter(k.split(".")[-2] for k in keys)
    print("      종류:", dict(kind))
