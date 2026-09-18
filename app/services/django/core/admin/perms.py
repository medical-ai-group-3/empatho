"""staff.extra_permissions 를 체크박스 격자로 고친다.

── 역할 기본 권한은 회색으로 보여준다 ────────────────────────────────
역할이 이미 주는 칸은 체크된 채로 잠가 둔다.

── 단독 권한 셋은 격자에 없다 ────────────────────────────────────────
검체 바인딩 · 불일치 해소 처분 · 리포트 잠금 해제. 
"""

from django import forms
from django.utils.html import format_html, format_html_join
from django.utils.safestring import mark_safe

from ..api.permissions import MATRIX, rule_for

ACTIONS = (("C", "만들기"), ("R", "보기"), ("U", "고치기"), ("D", "지우기"))

# 화면에 보일 한글 이름. 여기 없는 리소스는 영문 그대로 나온다 —
# MATRIX 에 리소스가 늘면 그때 한 줄 더한다.
RESOURCE_NAMES = {
    "patient": "환자", "reservation": "예약", "questionnaire": "문진",
    "exam_order": "검사 오더", "study": "검사(영상)", "ai_result": "AI 결과",
    "lesion": "병변", "assessment": "판정", "specimen_pathology": "검체 · 병리",
    "discordance_review": "불일치 검토", "followup": "추적 관찰",
    "clinical_decision": "임상 결정", "report": "리포트",
    "storage_object": "저장 파일", "patient_pii": "환자 개인정보",
    "notification": "알림", "consent": "동의",
}

# 개인 추가로 열 수 없는 것들. 격자 아래에 적어만 둔다
SOLO_NOTES = (
    ("검체 바인딩", "간호과 · 유방외과"),
    ("불일치 해소 처분", "유방외과"),
    ("리포트 열람 잠금 해제", "유방외과"),
)


class PermissionGrid(forms.Widget):
    """리소스 × CRUD 격자. 값은 {"resource": ["R", "U"]} 로 모은다."""

    def __init__(self, role=None, attrs=None):
        self.role = role
        super().__init__(attrs)

    # ── 읽기 ────────────────────────────────────────────────────
    def value_from_datadict(self, data, files, name):
        """체크된 칸만 모은다.

        역할이 이미 주는 칸은 **개인 추가로 저장하지 않는다.** 저장하면
        역할에서 그 권한을 빼도 이 사람만 계속 갖게 된다 — 「역할을 고쳤는데
        한 사람만 안 바뀐다」가 가장 찾기 어려운 종류다.
        """
        out = {}
        for resource in MATRIX:
            granted = self._role_actions(resource)
            picked = [
                action for action, _ in ACTIONS
                if action not in granted
                and f"{name}__{resource}__{action}" in data
            ]
            if picked:
                out[resource] = picked
        return out or None      # 빈 dict 보다 NULL 이 이 칸의 「없음」이다

    def _role_actions(self, resource):
        if not self.role:
            return ""
        try:
            return rule_for(resource, self.role).actions
        except KeyError:
            return ""

    # ── 그리기 ──────────────────────────────────────────────────
    def render(self, name, value, attrs=None, renderer=None):
        extra = value if isinstance(value, dict) else {}
        head = format_html_join("", "<th>{}</th>", ((label,) for _, label in ACTIONS))

        rows = []
        for resource in MATRIX:
            granted = self._role_actions(resource)
            cells = []
            for action, _ in ACTIONS:
                cells.append(self._cell(name, resource, action, granted, extra))
            rows.append(format_html(
                '<tr><th class="res">{}<span>{}</span></th>{}</tr>',
                RESOURCE_NAMES.get(resource, resource), resource,
                mark_safe("".join(cells)),
            ))

        solo = format_html_join(
            "", "<li><b>{}</b> — {}</li>",
            ((what, who) for what, who in SOLO_NOTES))

        return format_html(
            '<div class="permgrid">'
            '<p class="help">회색으로 체크된 칸은 <b>{}</b> 역할이 이미 가진 것입니다. '
            '개인에게 더 줄 것만 고르세요 — 뺄 수는 없습니다.</p>'
            '<table><thead><tr><th>리소스</th>{}</tr></thead><tbody>{}</tbody></table>'
            '<p class="help">아래 셋은 <b>개인 추가로 열 수 없습니다.</b> '
            '역할로만 정해집니다.</p><ul class="solo">{}</ul>'
            '{}</div>',
            self.role or "(역할 없음)", head, mark_safe("".join(rows)), solo,
            mark_safe(GRID_CSS),
        )

    def _cell(self, name, resource, action, granted, extra):
        if action in granted:
            # 역할이 이미 준 것 — 체크해 두고 잠근다. 이름을 안 주므로
            # 저장할 때 개인 추가로 섞여 들어가지 않는다
            return format_html(
                '<td class="has"><input type="checkbox" checked disabled '
                'title="{} 역할이 이미 가진 권한입니다"></td>', self.role or "")
        checked = action in (extra.get(resource) or [])
        return format_html(
            '<td><input type="checkbox" name="{}__{}__{}"{}></td>',
            name, resource, action, mark_safe(" checked" if checked else ""))


GRID_CSS = """
<style>
.permgrid table{border-collapse:collapse;margin:.5em 0;font-size:12px}
.permgrid th,.permgrid td{border:1px solid #ddd;padding:4px 8px;text-align:center}
.permgrid th.res{text-align:left;font-weight:600;white-space:nowrap}
.permgrid th.res span{display:block;font-weight:400;color:#888;font-size:11px}
.permgrid td.has{background:#f4f4f4}
.permgrid td.has input{opacity:.5}
.permgrid ul.solo{margin:.3em 0 0 1.2em;color:#666;font-size:12px}
.permgrid p.help{margin:.4em 0}
</style>
"""
