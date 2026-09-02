import hashlib, json, subprocess, sys, urllib.request, urllib.error
from pathlib import Path
gw, key, f, nparts = sys.argv[1], sys.argv[2], Path(sys.argv[3]).expanduser(), int(sys.argv[4])
raw = f.read_bytes(); dig = hashlib.sha256(raw).hexdigest()
pat, sco = "P-CHUNK", "STUDY-CHUNK"; pre = f"patients/{pat}/studies/{sco}"
mint = Path(__file__).parent / "mint_ticket.py"
def tok():
    return subprocess.run([sys.executable, str(mint), "--key", key,
        "--purpose", "wsi_upload", "--patient", pat, "--scope", sco,
        "--prefix", pre, "--max-bytes", str(len(raw)*2)],
        capture_output=True, text=True).stdout.strip()
def call(m, u, d=None, h=None):
    r = urllib.request.Request(u, data=d, method=m, headers=h or {})
    try:
        with urllib.request.urlopen(r, timeout=300) as res: return res.status, res.read()
    except urllib.error.HTTPError as e: return e.code, e.read()
print(f"파일 {f.name}  {len(raw):,} bytes  →  {nparts}조각")
st, b = call("POST", f"{gw}/svc/v1/upload/init",
             json.dumps({"filename": f.name}).encode(),
             {"Authorization": f"Bearer {tok()}", "Content-Type": "application/json"})
if st != 200: sys.exit(f"init 실패 {st}: {b}")
uid = json.loads(b)["upload_id"]; print(f"  개시 {uid}")
sz = (len(raw)+nparts-1)//nparts
order = list(range(nparts, 0, -1))          # 일부러 거꾸로 보낸다
for n in order:
    part = raw[(n-1)*sz : n*sz]
    st, b = call("PUT", f"{gw}/svc/v1/upload/{uid}/part/{n}", part,
                 {"Authorization": f"Bearer {tok()}"})
    if st != 200: sys.exit(f"조각 {n} 실패 {st}: {b}")
    print(f"  조각 {n}  {len(part):,} bytes")
print(f"  (보낸 순서 {order} — 거꾸로 보내도 순서대로 붙어야 한다)")
st, b = call("POST", f"{gw}/svc/v1/upload/{uid}/complete", b"",
             {"Authorization": f"Bearer {tok()}"})
if st != 201: sys.exit(f"complete 실패 {st}: {b}")
r = json.loads(b)
print(f"\n  201  {r['object_key']}")
print(f"  sha256 {'일치' if r['checksum_sha256']==dig else '불일치!'}")
print(f"  크기   {'일치' if r['byte_size']==len(raw) else '불일치!'}  {r['byte_size']:,}")
d = r.get("dicom")
print(f"  G-F7   {'인식' if d else '인식 못 함'}"
      + (f"  {d.get('modality')}  간격 {d.get('pixel_spacing_mm')}" if d else ""))
sys.exit(0 if r['checksum_sha256']==dig and r['byte_size']==len(raw) and d else 1)
