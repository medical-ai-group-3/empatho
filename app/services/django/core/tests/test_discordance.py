# -*- coding: utf-8 -*-
"""영상↔병리 자동 대조 규칙 — core/services/discordance.py.

규칙은 둘뿐이다.
  영상 의심(4a·4b·4c·5) + 병리 정상·양성(b1·b2)  → rule1 위양성 검토
  영상 저위험(1·2·3)   + 병리 악성(b5)          → rule2 위음성 검토

B3 · B4 는 규칙 밖이다 — 어느 쪽과 만나도 세우지 않는다.
"""
from django.test import TestCase
from django.utils import timezone

from core.models import (
    Assessment,
    DiscordanceFlag,
    ExamOrder,
    Lesion,
    Patient,
    Specimen,
    Study,
)
from core.services import discordance


class DiscordanceRuleTests(TestCase):
    """한 환자에 영상 최종 판정 하나 · 검체 하나를 두고 규칙만 본다."""

    def setUp(self):
        self.patient = Patient.objects.create(patient_number="D-TEST-001", sex="F")
        # ⚠ order_status="ordered" 는 ordered_by 를 요구한다
        #   (exam_order_requested_fields_ck). 이 테스트는 오더 상태와
        #   무관하므로 그 제약이 없는 requested 로 둔다.
        self.order = ExamOrder.objects.create(
            patient=self.patient, order_status="requested",
            modality="mammo", exam_purpose="screening",
        )
        self.study = Study.objects.create(
            patient=self.patient, exam_order=self.order, modality="mammo",
            read_status="finalized",
        )
        self.lesion = Lesion.objects.create(patient=self.patient, study=self.study)

    def _assess(self, category):
        """영상 최종 판정 한 행."""
        return Assessment.objects.create(
            study=self.study, lesion=self.lesion, read_stage="final",
            category=category, finalized_at=timezone.now(),
        )

    def _specimen(self, b_category, label="S-D-TEST-001"):
        """병리 확진이 끝난 검체 한 행."""
        return Specimen.objects.create(
            patient=self.patient, lesion=self.lesion, specimen_label=label,
            specimen_type="cnb", guidance_route="us",
            # 확진까지 끝난 검체라 accessioned 다(기본값이 없어 제약에 걸린다)
            accession_status="accessioned",
            b_category=b_category, finalized_at=timezone.now(),
        )

    # ── 1. 영상 의심 + 병리 양성 → 위양성 ────────────────────────
    def test_suspicious_imaging_with_benign_pathology_flags(self):
        self._assess("4b")
        specimen = self._specimen("b2")

        flag = discordance.evaluate(self.patient, specimen)

        self.assertIsNotNone(flag)
        self.assertEqual(DiscordanceFlag.objects.count(), 1)
        self.assertEqual(flag.violated_rule, "rule1")
        self.assertEqual(
            flag.review_note, "영상 의심(BI-RADS 4b) · 병리 B2 — 위양성 검토")
        # 「열림」은 closed_at 이 비어 있다는 뜻이다
        self.assertIsNone(flag.closed_at)
        # 환자로 찾으려면 lesion 이 있어야 한다
        self.assertEqual(flag.lesion_id, self.lesion.pk)

    # ── 2. 영상 저위험 + 병리 악성 → 위음성 ──────────────────────
    def test_low_risk_imaging_with_malignant_pathology_flags(self):
        self._assess("2")
        specimen = self._specimen("b5")

        flag = discordance.evaluate(self.patient, specimen)

        self.assertIsNotNone(flag)
        self.assertEqual(DiscordanceFlag.objects.count(), 1)
        self.assertEqual(flag.violated_rule, "rule2")
        self.assertEqual(
            flag.review_note, "영상 저위험(BI-RADS 2) · 병리 B5 — 위음성 검토")

    # ── 3. 같은 방향이면 안 세운다 ───────────────────────────────
    def test_agreeing_judgements_do_not_flag(self):
        self._assess("4b")
        specimen = self._specimen("b5")

        flag = discordance.evaluate(self.patient, specimen)

        self.assertIsNone(flag)
        self.assertEqual(DiscordanceFlag.objects.count(), 0)

    # ── 4. B3 은 규칙 밖 ─────────────────────────────────────────
    def test_b3_is_outside_the_rules(self):
        self._assess("4b")
        specimen = self._specimen("b3")

        flag = discordance.evaluate(self.patient, specimen)

        self.assertIsNone(flag)
        self.assertEqual(DiscordanceFlag.objects.count(), 0)

    # ── 5. 두 번 확정해도 하나 ───────────────────────────────────
    def test_reevaluating_does_not_duplicate(self):
        self._assess("4b")
        specimen = self._specimen("b2")

        first = discordance.evaluate(self.patient, specimen)
        second = discordance.evaluate(self.patient, specimen)

        self.assertIsNotNone(first)
        self.assertIsNone(second)
        self.assertEqual(DiscordanceFlag.objects.count(), 1)
