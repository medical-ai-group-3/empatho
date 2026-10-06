"""JSON 글상자를 격자로 고친다 — 과별 권한과 리소스 × CRUD 둘.

── DeptGrid · 과별 권한 (staff.extra_depts) ──────────────────────────
「이 사람은 영상의학과 화면도 쓴다」. 그 과의 매트릭스 행 **과** 화면 권한
키를 한 벌로 더한다. 소속 과는 잠가서 보여 준다.

병원 웹 메뉴가 화면 권한 키({과}.{화면}.{동작})로 돌기 때문에, 아래 CRUD
격자로 칸을 아무리 더해도 메뉴는 안 열린다 — 그래서 과 단위가 따로 있다.

── PermissionGrid · 리소스 × CRUD (staff.extra_permissions) ──────────
칸 하나를 더한다. 역할이 이미 주는 칸은 체크된 채로 잠가 둔다.
계정 상세에서는 「세부 권한 (고급)」으로 접혀 있다.

── 단독 권한 셋은 어느 격자에도 없다 ─────────────────────────────────
검체 바인딩 · 불일치 해소 처분 · 리포트 잠금 해제. IsRole 계열이라
account.role 만 본다 — 과별 권한으로도 안 열린다.
"""

from django import forms
from django.utils.html import format_html, format_html_join
from django.utils.safestring import mark_safe

from ..api.perms import ROLE_PERMS
from ..api.permissions import DEPT_ROLES, GRANTABLE_DEPTS, MATRIX, rule_for

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

#: 과 코드 → 화면에 보일 이름. GRANTABLE_DEPTS 에 없는 것(admin · patient ·
#: reception)도 목록 칸에서 옛 값을 읽을 수 있게 같이 둔다
DEPT_LABELS = {
    "nursing": "간호과", "radiology": "영상의학과",
    "surgery": "유방외과", "pathology": "병리과",
    "reception": "원무과", "admin": "관리자", "patient": "환자",
}


def dept_label(code):
    return DEPT_LABELS.get(code, code)


def dept_words(codes):
    return " · ".join(dept_label(c) for c in codes) or "없음"


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


# ── 과 단위 추가 권한 ────────────────────────────────────────────────
class DeptGrid(forms.Widget):
    """이 사람이 **한 벌로 더 보는 과**. 값은 ["radiology"] 로 모은다.

    아래 CRUD 격자와 목적이 다르다 — 저쪽은 칸 하나를 더하고, 이쪽은 과
    한 벌(그 과의 매트릭스 행 + 화면 권한 키)을 통째로 더한다. 병원 웹
    메뉴가 화면 권한 키로 도는 탓에, 칸 하나를 더해 봐야 메뉴는 안 열린다.

    소속 과는 **잠가서 체크된 채로** 보여 준다. 뺄 수 있는 값이 아니다 —
    소속을 바꾸려면 위의 「부서」를 바꾼다.
    """

    def __init__(self, role=None, attrs=None):
        self.role = role
        super().__init__(attrs)

    def value_from_datadict(self, data, files, name):
        picked = [d for d in GRANTABLE_DEPTS
                  if d != self.role and f"{name}__{d}" in data]
        return picked or None      # 빈 목록보다 NULL 이 이 칸의 「없음」이다

    def render(self, name, value, attrs=None, renderer=None):
        if self.role not in DEPT_ROLES:
            # 체크는 되는데 아무 일도 안 일어나는 칸을 그리지 않는다.
            # 관리자 권한은 부서가 아니라 문이고, 환자는 과가 없다
            return format_html(
                '<div class="deptgrid"><p class="help">'
                '<b>{}</b> 계정에는 과별 권한을 줄 수 없습니다.</p>{}</div>',
                dept_label(self.role) or "이 역할", mark_safe(DEPT_CSS))

        picked = set(value) if isinstance(value, (list, tuple)) else set()

        chips = [self._own_chip()] if self.role in GRANTABLE_DEPTS else []
        for dept in GRANTABLE_DEPTS:
            if dept != self.role:
                chips.append(self._chip(name, dept, dept in picked))

        return format_html(
            '<div class="deptgrid">'
            '<p class="help">소속 과는 잠겨 있습니다 — 바꾸려면 위의 '
            '「부서」를 고치세요. 여기서 고른 과는 <b>그 과의 화면과 권한을 '
            '한 벌로</b> 더합니다.</p>'
            '<div class="chips">{}</div>'
            '<p class="help">⚠ 관리자는 여기서 줄 수 없습니다. 단독 권한 셋'
            '(검체 바인딩 · 불일치 해소 처분 · 리포트 잠금 해제)도 열리지 '
            '않습니다 — 소속 과로만 정해집니다.</p>'
            '<p class="help">⚠ 저장하면 <b>그 사람은 다시 로그인해야 합니다.</b> '
            '쓰던 토큰은 바로 막힙니다.</p>{}</div>',
            mark_safe("".join(chips)), mark_safe(DEPT_CSS))

    def _own_chip(self):
        return format_html(
            '<label class="chip own"><input type="checkbox" checked disabled>'
            '<b>{}</b><span>소속</span></label>', dept_label(self.role))

    def _chip(self, name, dept, checked):
        return format_html(
            '<label class="chip"><input type="checkbox" name="{}__{}"{}>'
            '<b>{}</b><span>화면 {}개</span></label>',
            name, dept, mark_safe(" checked" if checked else ""),
            dept_label(dept), len(ROLE_PERMS.get(dept, [])))


DEPT_CSS = """
<style>
.deptgrid .chips{display:flex;flex-wrap:wrap;gap:8px;margin:.5em 0}
.deptgrid .chip{display:inline-flex;align-items:center;gap:6px;
  border:1px solid #ccc;border-radius:14px;padding:5px 12px;font-size:12px;
  cursor:pointer;background:#fff}
.deptgrid .chip:has(input:checked){border-color:#417690;background:#eef4f7}
.deptgrid .chip.own{cursor:default;background:#f4f4f4;color:#555}
.deptgrid .chip b{font-weight:600}
.deptgrid .chip span{color:#888}
.deptgrid p.help{margin:.4em 0}
</style>
"""


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
