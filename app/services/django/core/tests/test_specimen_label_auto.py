# -*- coding: utf-8 -*-
"""검체 라벨 자동 생성 — 비워 보내면 S-{채취일}-{환자번호}-{병변} (09-28)."""
from django.utils import timezone

from core.models import Lesion, Specimen
from core.tests.test_flow_0928_rad_path import _Base, _client, _data


class SpecimenLabelAutoTests(_Base):
    def setUp(self):
        super().setUp()
        self.lesion = Lesion.objects.create(study=self.study, patient=self.patient,
                                            modality="mammo", label="MAMMO-1", lesion_source="ai")

    def _bind(self, **extra):
        body = {"lesion_id": self.lesion.pk, "specimen_type": "core_needle",
                "guidance_route": "ultrasound", "collected_at": timezone.now().isoformat(), **extra}
        return _client(self.nurse).post("/api/v1/specimens/", body, format="json")

    def test_라벨을_비우면_서버가_만들고_겹치면_번호를_붙인다(self):
        day = f"{timezone.localdate():%Y%m%d}"
        r1, r2 = self._bind(), self._bind(specimen_label="")
        self.assertEqual(r1.status_code, 201, r1.content)
        self.assertEqual(_data(r1)["specimen_label"], f"S-{day}-P-B1-001-MAMMO-1")
        self.assertEqual(_data(r2)["specimen_label"], f"S-{day}-P-B1-001-MAMMO-1-2")

    def test_적어_보내면_그대로_쓴다(self):
        r = self._bind(specimen_label="S-HAND-1")
        self.assertEqual(r.status_code, 201, r.content)
        self.assertTrue(Specimen.objects.filter(specimen_label="S-HAND-1").exists())

    def test_이름없는_옛_병변은_모달리티_순번(self):
        self.lesion.label = None; self.lesion.lesion_index = 2; self.lesion.save()
        self.assertTrue(_data(self._bind())["specimen_label"].endswith("-MAMMO-3"))
