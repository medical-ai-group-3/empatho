import glob, io, json, os, time, urllib.request
BASE="http://127.0.0.1:8001"
def post(sock, path):
    b="----p"
    with open(path,"rb") as f: data=f.read()
    body=(f"--{b}\r\nContent-Disposition: form-data; name=\"image\"; filename=\"{os.path.basename(path)}\"\r\n"
          f"Content-Type: application/octet-stream\r\n\r\n").encode()+data+f"\r\n--{b}--\r\n".encode()
    r=urllib.request.Request(f"{BASE}/analyze/{sock}", data=body,
        headers={"Content-Type": f"multipart/form-data; boundary={b}"})
    t=time.perf_counter()
    with urllib.request.urlopen(r, timeout=900) as x: d=json.loads(x.read())
    return round(time.perf_counter()-t,2), d

files = sorted(glob.glob(os.path.expanduser("~/data/tiger/cellvit_detection/test/images/*.png")))
cand = files[::28][:10]
print("병리 후보", len(cand), "장")
best=[]
for p in cand:
    try:
        sec,d = post("1", p)
    except Exception as e:
        print("  ERR", os.path.basename(p)[:28], e); continue
    r = d.get("result") or {}
    if d.get("abstained"):
        print(f"  {os.path.basename(p)[:30]:32s} 기권 {d.get(\"reason\")}"); continue
    st=r.get("stroma_status"); stil=r.get("stil_percent")
    print(f"  {os.path.basename(p)[:30]:32s} {sec:6.2f}s stroma={st} stil={stil} cells={r.get(\"n_cells_total\")} tsr_t={r.get(\"tsr_tumor_percent\")}")
    if st=="ok" and stil: best.append((stil, p, r.get("n_cells_total")))
best.sort(reverse=True)
print("\n추천(sTIL 높은 순):")
for stil,p,n in best[:3]: print(f"   {os.path.basename(p)}  stil={stil}  cells={n}")
