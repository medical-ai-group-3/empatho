# -*- coding: utf-8 -*-
"""admin 화면이 쓰는 태그들.

전부 «파이썬에서만 할 수 있는 것»을 템플릿에 넘겨 주는 일만 한다. 모양은
템플릿과 CSS 가 정한다 — 여기서 색을 만들면 색을 바꿀 때 파이썬을 고치게 된다.
그래서 색도 «열쇠»(d-nursing)만 넘기고 실제 값은 CSS 에 둔다.
"""

from django import template

register = template.Library()

#: 상태 → (사람이 읽는 말, 색 열쇠). 색 값은 admin.css 의 .s-* 에 있다.
STATUS_LOOK = {
    "pending": ("승인 대기", "pending"),
    "active": ("승인됨", "active"),
    "rejected": ("거절됨", "rejected"),
    "suspended": ("정지됨", "suspended"),
}


@register.simple_tag
def account_rows(cl):
    """줄마다 화면에 필요한 것들.

    아바타 글자 · 부서 색 열쇠 · 상태 알약을 여기서 한 번에 만든다. 템플릿에
    if 를 여섯 벌 두면 줄마다 같은 판단을 다시 하게 되고, 부서가 하나 늘 때
    고칠 곳이 흩어진다.
    """
    from core.admin.edit import DEPT_NAMES

    dept_names = dict(DEPT_NAMES)
    out = []
    for obj in cl.result_list:
        staff = getattr(obj, "staff", None)
        dept = dept_names.get(obj.role, obj.role)
        label, tone = STATUS_LOOK.get(obj.account_status,
                                      (obj.account_status, "suspended"))
        out.append({
            "obj": obj,
            "name": staff.full_name if staff else "—",
            "number": staff.staff_number if staff else "—",
            "dept": dept,
            # 날짜 서식은 AccountAdmin.signed_up 것을 그대로 쓴다 — 여기서 또
            # 짜면 두 벌이 되고, 한쪽만 고쳐 놓고 한참 뒤에 어긋난 걸 본다
            "signed": cl.model_admin.signed_up(obj),
            # 아바타 글자. 부서 이름 첫 자라 「간」·「영」처럼 한 글자가 된다
            "initial": dept[:1],
            # 색은 열쇠만 넘긴다 — 값은 CSS 의 .d-* 에 있다
            "tone": obj.role,
            "status": label,
            "status_tone": tone,
            # 대기 · 승인됨 · 정지됨마다 놓을 단추가 다르다
            "can_approve": obj.account_status == "pending",
            "can_suspend": obj.account_status == "active",
            "can_restore": obj.account_status == "suspended",
        })
    return out
