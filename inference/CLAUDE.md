# empatho-inference

EMPATHO 유방암 검진 CDSS의 **GPU 추론 서버**. FastAPI로 소켓 1~5의 세그멘테이션·분류·정량만 담당한다.

## 이 레포가 하는 일 / 하지 않는 일

**한다**: 이미지 입력 → 세그멘테이션 마스크·분류·정량 값 산출, 기권(abstain) 판정, 재현용 버전 정보 반환.

**하지 않는다**:
- DB 쓰기 — Django 단독 담당. 이 서버는 결과를 반환만 한다
- 최종 의료 판정 — 모든 산출물은 제안·후보·플래그 (설계 원칙 1: "시스템은 판정하지 않는다")
- 파일 저장·전송 — Go + Garage/Orthanc 담당
- MedGemma 리포트 생성 (소켓 6) — Go가 Ollama로 별도 호출. 이 레포 범위 밖

## 실행 환경 (중요)

워크스테이션은 **비특권 Docker 컨테이너**다. 다음이 전부 불가능하다:
- Docker / docker-compose (`CapEff: 0000000000000000`, Docker-in-Docker 불가)
- systemd (PID 1 = sshd) → 프로세스 관리는 **supervisor**(pip 설치)
- 공인 인바운드 SSH → 배포는 **self-hosted GitHub Actions runner**(아웃바운드 전용)

GPU: RTX 5090 32GB (Blackwell, sm_120), torch 2.13+cu130 사전 설치.

⚠ `$HOME`이 컨테이너 재시작 후에도 유지되는지 **미확인**. 재생성되면 `~/app`·`~/actions-runner`·러너 등록이 전부 날아간다.

## 개발 워크플로

**워크스테이션에서 직접 코드를 편집하지 않는다.** 로컬 클론에서 편집·검증 후 push한다.


로컬 실행:
```powershell
.\.venv\Scripts\activate.ps1
python -m uvicorn main:app --host 127.0.0.1 --port 8055
```
(8001은 VSCode Remote-SSH 포트포워딩과 충돌할 수 있어 피한다. 로컬엔 모델이 없으므로 전 소켓이 `abstain_only:no_base`로 나오는 것이 정상.)

## 모델 소켓

| 소켓 | base_dir | prefix | 설명 |
|---|---|---|---|
| 1 | virchow2 | path_seg | 병리 분할 (Virchow2 + Efficient-UNet) |
| 2 | cellvit | path_cell | 병리 세포검출 (CellViT++) |
| 3 | medsam3 | mri_seg | MRI 병변 분할 |
| 4 | medsam3 | us_seg | 초음파 분할 |
| 5 | medsam3 | us_coral | 초음파 등급 (CORAL) |
| 4b | medsam3 | mammo | 유방 엑스레이 서술어 (경로 A) |

소켓 ID 집합은 `empatho-app`의 `mock_inference/main.py`와 **반드시 일치해야 한다**.

## 모델 가중치는 git에 넣지 않는다

`models/`는 `.gitignore` 대상. 가중치는 배포 파이프라인과 무관하게 워크스테이션 디스크에 직접 놓는다.

- 베이스: `~/workspace/MedSAM3/ckpt/` → `~/app/models/base/medsam3/` 심볼릭 링크
- 학습 결과(LoRA·헤드·thresholds.yaml): 같은 머신에서 학습하므로 링크 또는 복사
- 다른 머신에서 학습했다면 rsync

`/healthz`의 소켓 상태로 확인한다: `ready` / `abstain_only:no_base` / `abstain_only:no_weights`.

## 미해결 항목

- **추론 연결 방식 미확정** — 워크스테이션 인바운드 불가. Tailscale(userspace 모드, 코드 변경 0줄) vs pull 모드(작업을 꺼내오는 어댑터, 미구현) 중 정책 답 대기 중. 그때까지 `empatho-app`은 `mock` 모드로 개발
- **응답 계약 확장 필요** — API 명세서 v3 5-1절 기준 `model_name`·`model_version`·`lora_version`·`threshold_version`·`gate_flags` 반환해야 하나 현재 스텁은 `socket_id`·`abstained`·`reason`만 반환
- **MRI 소켓 활성화가 명세서와 충돌** — 명세서 v3(2026-08-19 합의)는 "MRI는 이번 기간 미학습·항상 기권"이나, 데이터 확보로 활성화함. 명세서 갱신 필요
- 병리 소켓(1·2) 베이스 미확보 — Virchow2/UNI2는 CC-BY-NC-ND, 라이선스 확인 필요