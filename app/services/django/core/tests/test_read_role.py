# -*- coding: utf-8 -*-
"""판독 확정은 역할로 막는다 — 권한 칸으로 열리면 안 된다.

study:U 하나가 업로드와 판독확정을 겸한다. 칸을 개인에게 주면 원무·간호도
판독을 확정하게 되므로, 칸은 그대로 두고 역할로 한 번 더 가른다.

⚠ **「403 이 아니다」로 단언하지 않는다.** 그러면 뷰가 500 으로 터져도 통과한다 —
  실제로 한 번 그렇게 써서 터진 것을 못 잡았다. 막히는 쪽은 403 과 코드까지,
  되는 쪽은 **실제로 바뀌었는지**까지 본다.
"""

import json

from django.test import TestCase

from core.api import auth
from core.models import Account, ExamOrder, Patient, Staff, Study


def _account(role, extra=None):
    a = Account.objects.create(login_id="u_" + role, role=role,
                               account_status="active", is_active=True)
    Staff.objects.create(account=a, full_name="아무개",
                         staff_number="S-" + role, extra_permissions=extra)
    return a


def _study(**kw):
    """검사 하나.

    order_status='ordered' 는 modality · exam_purpose · ordered_by 셋이 다
    차야 한다 (exam_order_requested_fields_ck). 지시의를 빠뜨리면 CHECK 에 걸린다.
    """
    p = Patient.objects.create(patient_number=kw.pop("no", "P-READ-1"))
    doctor = _account("surgery").staff
    o = ExamOrder.objects.create(patient=p, order_status="ordered",
                                 modality="mammo", exam_purpose="screening",
                                 ordered_by=doctor)
    return Study.objects.create(patient=p, exam_order=o, modality="mammo", **kw)


class ReadRoleTests(TestCase):
    def _hdr(self, account):
        return {"HTTP_AUTHORIZATION": "Bearer " + auth.issue_access(account)}

    def _patch(self, account, url, body=None):
        return self.client.patch(url, content_type="application/json",
                                 data=json.dumps(body or {}), **self._hdr(account))

    def _forbidden(self, res, code="ROLE_FORBIDDEN"):
        self.assertEqual(res.status_code, 403, res.content[:200])
        self.assertEqual(res.json()["error"]["code"], code)

    # ── 막는 길 — 이 파일의 이유 ────────────────────────────────
    def test_칸을_개인에게_줘도_판독_확정은_막힌다(self):
        s = _study()
        nurse = _account("nursing", extra={"study": ["U"], "assessment": ["U"]})
        self._forbidden(self._patch(nurse, f"/api/v1/studies/{s.pk}/finalize"))

    def test_칸을_줘도_임시저장이_막힌다(self):
        s = _study()
        nurse = _account("nursing", extra={"assessment": ["U"]})
        res = self.client.put(f"/api/v1/studies/{s.pk}/assessment/draft",
                              content_type="application/json", data="{}",
                              **self._hdr(nurse))
        self._forbidden(res)

    def test_병리_확정도_역할로_막힌다(self):
        nurse = _account("nursing", extra={"specimen_pathology": ["U"]})
        self._forbidden(self._patch(nurse, "/api/v1/specimens/1/finalize"))

    def test_영상은_병리_확정을_못_한다(self):
        """과가 달라도 막힌다 — 판독은 그 과 의사의 일이다."""
        rad = _account("radiology")
        self._forbidden(self._patch(rad, "/api/v1/specimens/1/finalize"))

    # ── 되는 길 — 실제로 바뀌는지까지 ──────────────────────────
    def test_radiology_는_임시저장한_판정을_확정한다(self):
        """임시저장 → 확정을 이어서 태운다.

        확정은 draft 인 판정이 있어야 한다 — 없으면 VALIDATION_ERROR 다.
        한 걸음만 떼어 부르면 그 앞 단계가 빠진 것을 못 본다.
        """
        s = _study(read_status="draft")
        rad = _account("radiology")

        draft = self.client.put(f"/api/v1/studies/{s.pk}/assessment/draft",
                                content_type="application/json",
                                data=json.dumps({"birads_category": "2"}),
                                **self._hdr(rad))
        self.assertIn(draft.status_code, (200, 201), draft.content[:300])

        res = self._patch(rad, f"/api/v1/studies/{s.pk}/finalize")
        self.assertEqual(res.status_code, 200, res.content[:300])

        s.refresh_from_db()
        self.assertEqual(s.read_status, "finalized",
                         "200 인데 read_status 가 안 바뀌었다")

    def test_같은_계정으로_업로드_조회는_된다(self):
        """칸을 지우지 않은 이유가 이것이다 — 지우면 기사까지 막힌다."""
        s = _study()
        nurse = _account("nursing", extra={"study": ["U"]})
        res = self.client.get(f"/api/v1/studies/{s.pk}/upload", **self._hdr(nurse))

        self.assertEqual(res.status_code, 200, res.content[:300])

    # ── 리포트 잠금 ────────────────────────────────────────────
    def test_잠금_해제는_유방외과만(self):
        """CanUnlockReport 가 정의만 되고 뷰에 안 붙어 있었다 —
        명세 §11.5 「유방외과 단독」이 코드에서 성립하지 않던 자리다."""
        rad = _account("radiology", extra={"report": ["U"]})
        self._forbidden(self._patch(rad, "/api/v1/reports/1/unlock"),
                        code="UNLOCK_ROLE_ONLY_SURGERY")
