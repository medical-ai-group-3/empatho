#!/usr/bin/env python
"""
SAM3 검출 학습 설정을 만든다 — 기존 설정을 읽어 필요한 곳만 고친다.

왜 이렇게
  roboflow_v100_full_ft_100_images.yaml 이 우리 과제와 가장 가깝다.
    · 마스크 없이 박스만으로 학습한다 (no mask loss)
    · 소량 데이터 미세조정용이다
  539줄을 손으로 옮겨 적으면 오타 하나로 무너진다. 읽어서 고친다.

무엇을 고치나
  1. 데이터 경로     roboflow 경로 -> 우리 COCO 폴더
  2. 사전학습 가중치  medsam3_merged.pt 를 얹는다 (없으면 무작위 초기값이다)
  3. 백본 동결       lr_vision_backbone / lr_language_backbone -> 0
  4. DecodeRle 제거  우리 JSON 에 segmentation 이 없다
  5. SLURM 배열 제거  supercategory / job_array 지시를 걷어낸다
  6. BPE 경로        실제 파일 위치로
  7. 로그 폴더

바꾼 것을 전부 출력한다. 조용히 넘어가는 변경이 없다.
끝에 남은 자리표시자를 검사해 하나라도 있으면 경고한다.

사용
  python3 make_train_cfg.py            # 미리보기
  python3 make_train_cfg.py --go       # 파일로 쓴다
"""

import argparse
import importlib
import sys
from pathlib import Path

try:
    import yaml
except ImportError:
    sys.exit("PyYAML 없음  ->  pip install pyyaml")

HOME = Path.home()
SRC = "sam3/train/configs/roboflow_v100/roboflow_v100_full_ft_100_images.yaml"

changes = []


def note(what, old, new):
    changes.append((what, old, new))


# ── 트리 훑기 ────────────────────────────────────────────────────────────────
def walk(node, fn, path=""):
    """모든 (부모, 키, 경로) 를 방문한다. fn 이 값을 바꿔도 된다."""
    if isinstance(node, dict):
        for k in list(node.keys()):
            fn(node, k, f"{path}.{k}")
            walk(node[k], fn, f"{path}.{k}")
    elif isinstance(node, list):
        for i in range(len(node)):
            fn(node, i, f"{path}[{i}]")
            walk(node[i], fn, f"{path}[{i}]")


def retarget_paths(cfg, ann_train, ann_val, img_train, img_val):
    """
    roboflow 경로를 우리 것으로 바꾼다.
    트리 모양을 모르는 채로 값의 생김새만 보고 찾는다 — 설정 구조가 달라져도 버틴다.
    """
    def fix(parent, key, path):
        v = parent[key]
        if not isinstance(v, str):
            return
        if "roboflow_vl_100_root" not in v and "supercategory" not in v:
            return
        low = v.rstrip("/")
        if low.endswith("train/_annotations.coco.json"):
            new = ann_train
        elif low.endswith(("test/_annotations.coco.json",
                           "valid/_annotations.coco.json")):
            new = ann_val
        elif low.endswith("/train"):
            new = img_train
        elif low.endswith(("/test", "/valid")):
            new = img_val
        else:
            return
        parent[key] = new
        note(f"경로 {path}", v, new)
    walk(cfg, fix)


def drop_transform(cfg, needle):
    """변환 목록에서 특정 _target_ 을 가진 항목을 뺀다."""
    n = [0]

    def prune(node):
        if isinstance(node, dict):
            for k in list(node.keys()):
                node[k] = prune(node[k])
        elif isinstance(node, list):
            keep = []
            for item in node:
                if isinstance(item, dict):
                    t = item.get("_target_")
                    if isinstance(t, str) and t.endswith(needle):
                        n[0] += 1
                        continue
                keep.append(prune(item))
            return keep
        return node

    prune(cfg)
    if n[0]:
        note(f"변환 제거 {needle}", f"{n[0]}곳", "삭제")
    return n[0]


def resolve_target(t):
    """hydra 가 _target_ 을 찾을 수 있는지 미리 확인한다."""
    if not isinstance(t, str) or "." not in t:
        return False, "형식이 아니다"
    mod, _, attr = t.rpartition(".")
    try:
        m = importlib.import_module(mod)
    except Exception as e:
        return False, f"모듈 임포트 실패 {type(e).__name__}: {str(e)[:60]}"
    if not hasattr(m, attr):
        return False, f"{mod} 에 {attr} 가 없다"
    return True, ""


def collect_targets(cfg):
    """(경로, 대상) 쌍을 모두 모은다."""
    out = []

    def fn(parent, key, path):
        if key == "_target_" and isinstance(parent[key], str):
            out.append((path, parent[key]))
    walk(cfg, fn)
    return out


def drop_bad_targets(cfg, bad_targets):
    """
    목록(list) 안에 있으면서 대상이 없는 항목을 뺀다.
    변환 목록처럼 항목 하나가 빠져도 되는 곳만 정리된다.
    """
    bad = set(bad_targets)
    removed = []

    def prune(node):
        if isinstance(node, dict):
            for k in list(node.keys()):
                node[k] = prune(node[k])
        elif isinstance(node, list):
            keep = []
            for item in node:
                if isinstance(item, dict) and item.get("_target_") in bad:
                    removed.append(item["_target_"])
                    continue
                keep.append(prune(item))
            return keep
        return node

    prune(cfg)
    return removed


def setval(cfg, dotted, new, why=""):
    """점 경로로 값을 덮어쓴다. 중간 경로가 없으면 만든다."""
    parts = dotted.split(".")
    node = cfg
    for p in parts[:-1]:
        if not isinstance(node.get(p), dict):
            node[p] = {}
        node = node[p]
    old = node.get(parts[-1], "(없음)")
    node[parts[-1]] = new
    note(dotted + (f"  — {why}" if why else ""), old, new)
    return old


def getpath(cfg, dotted):
    node = cfg
    for p in dotted.split("."):
        if not isinstance(node, dict) or p not in node:
            return None
        node = node[p]
    return node


def head_comments(text):
    """맨 위 주석을 살린다 — hydra 는 '# @package _global_' 을 읽는다."""
    out = []
    for ln in text.splitlines():
        s = ln.strip()
        if s.startswith("#") or not s:
            out.append(ln)
            continue
        break
    return "\n".join(out).rstrip() + "\n"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", default=SRC)
    ap.add_argument("--out", default="configs_mammo/mammo_det.yaml")
    ap.add_argument("--det", default=str(HOME / "workspace/breast/mammo/det"))
    ap.add_argument("--ckpt",
                    default=str(HOME / "workspace/breast/mammo/ckpt/medsam3_merged.pt"))
    ap.add_argument("--bpe",
                    default=str(HOME / "workspace/MedSAM3/sam3/assets/bpe_simple_vocab_16e6.txt.gz"))
    ap.add_argument("--logdir", default=str(HOME / "workspace/breast/mammo/det_run"))
    ap.add_argument("--epochs", type=int, default=20)
    ap.add_argument("--unfreeze-backbone", action="store_true",
                    help="백본도 설정 기본 학습률로 함께 학습한다 (기본은 동결)")
    ap.add_argument("--drop-missing", action="store_true",
                    help="존재하지 않는 _target_ 을 가진 목록 항목을 뺀다")
    ap.add_argument("--no-check-targets", action="store_true",
                    help="_target_ 존재 확인을 건너뛴다 (sam3 임포트가 안 될 때)")
    ap.add_argument("--go", action="store_true", help="파일로 쓴다")
    a = ap.parse_args()

    src = Path(a.src)
    if not src.is_file():
        sys.exit(f"원본 설정이 없다: {src}")
    for p, what in ((Path(a.ckpt), "사전학습 체크포인트"), (Path(a.bpe), "BPE 파일")):
        if not p.is_file():
            sys.exit(f"{what}가 없다: {p}")

    det = Path(a.det)
    ann_train = str(det / "annotations/train.json")
    ann_val = str(det / "annotations/val.json")
    img_train = str(det / "images/train")
    img_val = str(det / "images/test")

    text = src.read_text(encoding="utf-8")
    header = head_comments(text)
    cfg = yaml.safe_load(text)
    if not isinstance(cfg, dict):
        sys.exit("설정을 읽지 못했다 — YAML 최상위가 사전이 아니다")

    print("=" * 76)
    print("SAM3 검출 학습 설정 생성")
    print("=" * 76)
    print(f"  원본  {src}")
    print(f"  출력  {a.out}")
    for p in (ann_train, ann_val):
        if not Path(p).is_file():
            print(f"  ! 아직 없다: {p}   (make_coco.py 가 도는 중이면 정상)")

    # 1. 데이터 경로
    retarget_paths(cfg, ann_train, ann_val, img_train, img_val)

    # 2. 기본 경로
    setval(cfg, "paths.experiment_log_dir", a.logdir)
    setval(cfg, "paths.bpe_path", a.bpe)
    # 원본 데이터 뿌리는 이제 아무도 안 쓴다. 자리표시자만 남으면 헷갈리니 채운다.
    if getpath(cfg, "paths.roboflow_vl_100_root") is not None:
        setval(cfg, "paths.roboflow_vl_100_root", str(det), why="참조 없음, 자리만 채움")

    # 3. 사전학습 가중치 — 이게 빠지면 무작위 초기값에서 학습한다
    setval(cfg, "trainer.checkpoint.model_weight_initializer", {
        "_partial_": True,
        "_target_": "sam3.train.utils.checkpoint_utils.load_state_dict_into_model",
        "strict": False,
        "state_dict": {
            "_target_": "sam3.train.utils.checkpoint_utils.load_checkpoint_and_apply_kernels",
            "checkpoint_path": a.ckpt,
            "ckpt_state_dict_keys": ["model"],
        },
    }, why="사전학습 가중치")

    # 4. 백본 동결
    if a.unfreeze_backbone:
        note("백본", "동결", "학습 (설정 기본 학습률 유지)")
    else:
        if getpath(cfg, "scratch.lr_vision_backbone") is not None:
            setval(cfg, "scratch.lr_vision_backbone", 0.0, why="시각 백본 동결")
        if getpath(cfg, "scratch.lr_language_backbone") is not None:
            setval(cfg, "scratch.lr_language_backbone", 0.0, why="언어 백본 동결")

    # 5. 마스크 없는 학습
    if getpath(cfg, "scratch.enable_segmentation") is not None:
        setval(cfg, "scratch.enable_segmentation", False, why="마스크 없음")
    drop_transform(cfg, "DecodeRle")

    # 6. 에폭
    if getpath(cfg, "scratch.max_epochs") is not None:
        setval(cfg, "scratch.max_epochs", a.epochs)

    # 7. SLURM 배열 흔적
    for key, new, why in (("roboflow_train.supercategory", "mammo", "배열 인덱스 제거"),
                          ("roboflow_train.num_images", None, "전부 사용")):
        if getpath(cfg, key) is not None or key.split(".")[-1] in (
                getpath(cfg, key.rsplit(".", 1)[0]) or {}):
            setval(cfg, key, new, why=why)

    # 8. 모든 _target_ 이 실제로 존재하는지 미리 확인한다.
    #    hydra 는 실행 시점에야 이걸 찾으므로, 안 하면 밤새 돌린 뒤에 터진다.
    if not a.no_check_targets:
        print("\n■ _target_ 존재 확인")
        targets = collect_targets(cfg)
        bad = []
        for path, t in targets:
            ok_t, why = resolve_target(t)
            if not ok_t:
                bad.append((path, t, why))
        print(f"  전체 {len(targets)}개 중 확인 불가 {len(bad)}개")
        for path, t, why in bad:
            print(f"    {t}")
            print(f"        {path}")
            print(f"        {why}")
        if bad:
            if a.drop_missing:
                removed = drop_bad_targets(cfg, [t for _, t, _ in bad])
                for t in removed:
                    note("존재하지 않는 변환 제거", t, "삭제")
                still = [t for _, t, _ in bad if t not in removed]
                if still:
                    print(f"\n  ! 목록 밖에 있어 뺄 수 없는 것 {len(still)}개:")
                    for t in still:
                        print(f"      {t}")
            else:
                print("\n  --drop-missing 을 붙이면 목록 안의 항목은 자동으로 뺀다.")

    print(f"\n■ 변경 {len(changes)}건")
    for what, old, new in changes:
        o, n = str(old), str(new)
        print(f"  {what}")
        print(f"      {o if len(o) <= 58 else o[:55] + '...'}")
        print(f"   -> {n if len(n) <= 58 else n[:55] + '...'}")

    body = yaml.safe_dump(cfg, sort_keys=False, allow_unicode=True,
                          default_flow_style=False, width=200)
    out_text = header + "\n" + body

    # 되읽기 — 우리가 쓴 것이 다시 읽히는지 확인한다
    try:
        back = yaml.safe_load(out_text)
    except Exception as e:
        sys.exit(f"\n! 결과가 다시 읽히지 않는다: {type(e).__name__}: {e}")

    # 검사는 '정의' 가 아니라 '참조' 를 본다.
    #   paths.roboflow_vl_100_root 라는 키가 남아 있는 것은 무해하다.
    #   ${paths.roboflow_vl_100_root} 로 그걸 가리키는 곳이 남아 있으면 놓친 것이다.
    print(f"\n■ 검사")
    ok = True
    # 치명적인 것만 막는다. 풀 수 없는 참조가 남으면 hydra 가 실행 시점에 죽는다.
    FATAL = (("${paths.roboflow_vl_100_root}", "되돌리지 못한 데이터 경로가 있다"),
             ("${submitit", "SLURM 배열 값을 아직 참조한다"),
             ("${all_roboflow_supercategories", "풀 수 없는 배열 조회가 남아 있다"),
             ("<YOUR", "채우지 않은 자리표시자가 남아 있다"),
             ("DecodeRle", "RLE 해독 변환이 남아 있다"))
    # 해석은 되지만 눈으로 확인할 값. 막지는 않는다.
    WARN = (("${roboflow_train.supercategory", "'mammo' 로 해석된다 — 경로가 아니면 무해하다"),)

    def show_lines(needle, limit=5):
        hit = [(i + 1, ln.strip()) for i, ln in enumerate(out_text.splitlines())
               if needle in ln]
        for no, ln in hit[:limit]:
            print(f"        {no:4d}| {ln[:96]}")
        if len(hit) > limit:
            print(f"        ... {len(hit) - limit}줄 더")

    for needle, why in FATAL:
        c = out_text.count(needle)
        print(f"  {'OK ' if c == 0 else '!! '}{needle:32s} {c}곳"
              + ("" if c == 0 else f"   <- {why}"))
        if c:
            ok = False
            show_lines(needle)

    for needle, why in WARN:
        c = out_text.count(needle)
        if c:
            print(f"  ?  {needle:32s} {c}곳   <- {why}")
            show_lines(needle)

    init = getpath(back, "trainer.checkpoint.model_weight_initializer")
    good_init = isinstance(init, dict) and \
        init.get("state_dict", {}).get("checkpoint_path") == a.ckpt
    print(f"  {'OK ' if good_init else '!! '}{'사전학습 가중치 경로':24s} "
          f"{'연결됨' if good_init else '연결 안 됨 — 무작위 초기값에서 학습하게 된다'}")
    ok = ok and good_init

    if "${" in out_text:
        n = out_text.count("${")
        print(f"  OK  {'보간 표현식':24s} {n}곳 보존")

    if not a.go:
        print("\n" + "=" * 76)
        print("미리보기다. 파일로 쓰려면 --go 를 붙여라.")
        print("=" * 76)
        return
    if not ok:
        sys.exit("\n! 검사를 통과하지 못했다 — 파일을 쓰지 않는다.")

    out = Path(a.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(out_text, encoding="utf-8")
    print(f"\n  -> {out}   ({len(out_text.splitlines())}줄)")
    print("\n  학습 실행:")
    print(f"    python3 sam3/train/train.py -c {out} --use-cluster 0 --num-gpus 1")


if __name__ == "__main__":
    main()
