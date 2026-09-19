"""소켓 번호 → 그 모달리티의 프롬프트 모듈.

report.py 가 이 표로 소켓을 찾는다. 모달리티를 추가하면
import 하고 MODULES 에 더한다 — 표는 SOCKET_IDS 로 자동으로 만들어진다.
"""
from prompts import mammo, mri, us, pathology, summary

MODULES = (us, mammo, mri, pathology, summary)

PROMPTS = {sid: mod for mod in MODULES for sid in mod.SOCKET_IDS}

# 앱 서버는 모달리티 이름으로 부르기 때문에 번호로 불러도 깨지지않게 둘 다 받음
PROMPTS.update(
    {
        "us": us, 
        "mammo": mammo, 
        "mri": mri, 
        "pathology": pathology, 
        "summary": summary
        }
    )