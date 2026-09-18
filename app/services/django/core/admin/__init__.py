"""Django admin — Django 가 이 패키지를 불러온다.

  site.py    AdminSite — 제목 · 사이드바 · 커스텀 화면 주소
  edit.py    데이터를 고치는 화면 (ModelAdmin 들)
  perms.py   개인 추가 권한 격자 위젯
  views.py   우리가 만든 화면 — 대시보드 · 서버 상태 · 계정 승인 · DB 조회

edit 를 여기서 불러오는 것으로 등록이 일어난다. 이름을 그대로 내보내므로
바깥에서는 `from core.admin import AccountAdmin` 이 전과 같이 된다.
"""

from .edit import AccountAdmin, StaffAdmin, StaffForm  # noqa: F401
