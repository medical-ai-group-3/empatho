"""소켓 번호 → 그 모달리티의 프롬프트 모듈.

report.py 가 이 표로 소켓을 찾는다. 모달리티를 추가하면
import 하고 MODULES 에 더한다 — 표는 SOCKET_IDS 로 자동으로 만들어진다.
"""
from prompts import mammo, mri, us, pathology

# 병리(소켓 1·2)는 아직 넣지 않는다 — sTIL 을 임상 척도로 어떻게 환산할지
# 병리 담당자 답을 기다리는 중이다(2026-09-09). 그때까지 /report/1·2 는
# unknown_socket 으로 기권한다. pathology.py 가 준비되면 두 줄을 되돌린다.
MODULES = (us, mammo, mri, pathology)

PROMPTS = {sid: mod for mod in MODULES for sid in mod.SOCKET_IDS}