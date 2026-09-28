# -*- coding: utf-8 -*-
"""초음파 여러 장 판독 · 병변 목록 필터 · malignancy_p 비노출 · BI-RADS 정규화.

    초음파는 영상 한 장이 판독 한 번이라 한 검사에 AiResult 가 여럿이다.
      - 판독 화면(GET /radiology/studies/{id}/read)은 ai_results 로 전부 준다.
        ai_results[].source_object == images[].storage_object_id
      - 장마다 도는 병변 저장이 서로의 병변을 지우면 안 된다.
"""
from datetime import date

from django.test import TestCase
from rest_framework.test import APIClient

from core import tasks
from core.api.auth import issue_access
from core.models import (Account, AiResult, ExamOrder, Lesion, Patient,
                         PatientPii, Staff, StorageObject, Study)
from core.serializers import LesionSerializer


def _client_for(account):
    c = APIClient()
    c.credentials(HTTP_AUTHORIZATION="Bearer " + issue_access(account))
    return c


def _us_result(found=True, display="4a"):
    return {"result": {
        "lesion_found": found,
        "shape": {"max_diameter_px": 42.0},
        "grade": {"display": display, "confidence": "보통"},
    }}


class _Base(TestCase):
    modality = "us"

    def setUp(self):
        self.account = Account.objects.create(
            login_id=f"rad-multi-{self.modality}", role="radiology",
            account_status="active", is_active=True)
        Staff.objects.create(account=self.account, staff_number=f"RAD-M-{self.modality}",
                             full_name="다장 판독")
        self.patient = Patient.objects.create(patient_number=f"P-MULTI-{self.modality}")
        PatientPii.objects.create(patient=self.patient, name="다장환자",
                                  birth_date=date(1980, 1, 1), phone="010-0000-0000")
        order = ExamOrder.objects.create(
            patient=self.patient, order_status="ordered", modality=self.modality,
            exam_purpose="diagnostic", ordered_by=self.account.staff)
        self.study = Study.objects.create(patient=self.patient, exam_order=order,
                                          modality=self.modality)
        self.client = _client_for(self.account)

    def _obj(self, key):
        return StorageObject.objects.create(study=self.study, bucket="empatho-original",
                                            object_key=f"study/{self.study.pk}/{key}.png")

    def _ai(self, source, result, status="done"):
        return AiResult.objects.create(patient=self.patient, study=self.study,
                                       source_object=source, result=result,
                                       run_status=status)


class UltrasoundMultiImageTests(_Base):
    def setUp(self):
        super().setUp()
        self.img1 = self._obj("a")
        self.img2 = self._obj("b")
        self.ai1 = self._ai(self.img1, _us_result(display="3"))
        self.ai2 = self._ai(self.img2, _us_result(display="4b"))

    def test_장마다_병변이_남고_이름이_겹치지_않는다(self):
        tasks._store_lesions(self.ai1)
        tasks._store_lesions(self.ai2)
        rows = Lesion.objects.filter(study=self.study).order_by("lesion_index")
        self.assertEqual([l.label for l in rows], ["US-1", "US-2"])
        self.assertEqual([l.ai_result_id for l in rows], [self.ai1.pk, self.ai2.pk])
        self.assertEqual([l.birads_model for l in rows], ["3", "4b"])
        self.assertEqual(rows[1].detail["source_object"], self.img2.pk)

    def test_같은_장을_다시_돌리면_그_장의_병변만_바뀐다(self):
        tasks._store_lesions(self.ai1)
        tasks._store_lesions(self.ai2)
        rerun = self._ai(self.img1, _us_result(display="5"))
        tasks._store_lesions(rerun)
        rows = Lesion.objects.filter(study=self.study).order_by("lesion_index")
        self.assertEqual([(l.label, l.ai_result_id) for l in rows],
                         [("US-1", rerun.pk), ("US-2", self.ai2.pk)])

    def test_사람이_그린_병변은_지우지_않는다(self):
        manual = Lesion.objects.create(study=self.study, patient=self.patient,
                                       lesion_source="manual")
        tasks._store_lesions(self.ai1)
        tasks._store_lesions(self._ai(self.img1, _us_result()))
        self.assertTrue(Lesion.objects.filter(pk=manual.pk).exists())

    def test_판독화면이_장마다_결과를_준다(self):
        res = self.client.get(f"/api/v1/radiology/studies/{self.study.pk}/read")
        self.assertEqual(res.status_code, 200)
        data = res.json()["data"]
        # 옛 화면용 칸은 그대로 — 가장 최근 것
        self.assertEqual(data["latest_ai_result"]["ai_result_id"], self.ai2.pk)
        # 전부 최신순, 모양은 latest_ai_result 와 같다
        self.assertEqual([r["ai_result_id"] for r in data["ai_results"]],
                         [self.ai2.pk, self.ai1.pk])
        self.assertEqual(set(data["ai_results"][0]), set(data["latest_ai_result"]))
        # 화면이 짝 짓는 열쇠: ai_results[].source_object == images[].storage_object_id
        image_ids = [i["storage_object_id"] for i in data["images"]]
        self.assertEqual(image_ids, [self.img1.pk, self.img2.pk])
        self.assertEqual({r["source_object"] for r in data["ai_results"]}, set(image_ids))

    def test_판독이_없으면_빈_목록(self):
        AiResult.objects.all().delete()
        data = self.client.get(
            f"/api/v1/radiology/studies/{self.study.pk}/read").json()["data"]
        self.assertIsNone(data["latest_ai_result"])
        self.assertEqual(data["ai_results"], [])


class MalignancyHiddenTests(_Base):
    def test_병변_직렬화에_malignancy_p_가_없다(self):
        lesion = Lesion.objects.create(study=self.study, patient=self.patient,
                                       lesion_source="ai", malignancy_p="0.830")
        data = LesionSerializer(lesion).data
        self.assertNotIn("malignancy_p", data)
        self.assertIn("mesh", data)   # surgery 쪽(메시 포함) 직렬화기를 쓴다

        self._obj("a")
        read = self.client.get(
            f"/api/v1/radiology/studies/{self.study.pk}/read").json()["data"]
        self.assertNotIn("malignancy_p", read["lesions"][0])

        listed = self.client.get(f"/api/v1/lesions/?patient={self.patient.pk}").json()["data"]
        items = listed["results"] if isinstance(listed, dict) else listed
        self.assertNotIn("malignancy_p", items[0])


class LesionListFilterTests(_Base):
    def setUp(self):
        super().setUp()
        other_order = ExamOrder.objects.create(
            patient=self.patient, order_status="ordered", modality="us",
            exam_purpose="diagnostic", ordered_by=self.account.staff)
        self.study2 = Study.objects.create(patient=self.patient, exam_order=other_order,
                                           modality="us")
        other = Patient.objects.create(patient_number="P-MULTI-OTHER")
        self.l_b = Lesion.objects.create(study=self.study, patient=self.patient,
                                         lesion_index=1, lesion_source="ai")
        self.l_a = Lesion.objects.create(study=self.study, patient=self.patient,
                                         lesion_index=0, lesion_source="ai")
        self.l_s2 = Lesion.objects.create(study=self.study2, patient=self.patient,
                                          lesion_index=0, lesion_source="ai")
        other_study = Study.objects.create(patient=other, exam_order=ExamOrder.objects.create(
            patient=other, order_status="ordered", modality="us",
            exam_purpose="diagnostic", ordered_by=self.account.staff), modality="us")
        self.l_other = Lesion.objects.create(study=other_study, patient=other,
                                             lesion_source="ai")

    def _ids(self, query):
        res = self.client.get(f"/api/v1/lesions/{query}")
        self.assertEqual(res.status_code, 200, res.content)
        data = res.json()["data"]
        items = data["results"] if isinstance(data, dict) else data
        return [l["lesion_id"] for l in items]

    def test_조건_없으면_빈_목록(self):
        self.assertEqual(self._ids(""), [])

    def test_환자로_거르고_순서를_못박는다(self):
        self.assertEqual(self._ids(f"?patient={self.patient.pk}"),
                         [self.l_a.pk, self.l_b.pk, self.l_s2.pk])

    def test_검사로_거른다(self):
        self.assertEqual(self._ids(f"?study={self.study2.pk}"), [self.l_s2.pk])

    def test_숫자가_아니면_400(self):
        res = self.client.get("/api/v1/lesions/?patient=abc")
        self.assertEqual(res.status_code, 400)

    def test_단건_조회는_필터와_무관하다(self):
        res = self.client.get(f"/api/v1/lesions/{self.l_other.pk}/")
        self.assertEqual(res.status_code, 200)


class MriBiradsTests(_Base):
    modality = "mri"

    def test_병변_등급을_옮기고_모르는_값은_비운다(self):
        src = self._obj("s")
        ai = self._ai(src, {"result": {"tumor": {"lesions": [
            {"birads": "4A"}, {"birads": 5}, {"birads": "weird"}, {}]}}})
        tasks._store_lesions(ai)
        rows = Lesion.objects.filter(ai_result=ai).order_by("lesion_index")
        self.assertEqual([l.birads_model for l in rows], ["4a", "5", None, None])
        self.assertEqual(rows[2].detail["birads_raw"], "weird")
        self.assertNotIn("birads_raw", rows[3].detail)


class BiradsHelperTests(TestCase):
    def test_정규화(self):
        self.assertEqual(tasks._birads("BI-RADS 4c"), "4c")
        self.assertEqual(tasks._birads(3), "3")
        self.assertIsNone(tasks._birads(None))
        self.assertIsNone(tasks._birads(True))
        self.assertIsNone(tasks._birads("7"))

    def test_섞인_형이어도_비교가_터지지_않는다(self):
        self.assertGreater(tasks._birads_rank("5"), tasks._birads_rank(4))
        self.assertGreater(tasks._birads_rank("4b"), tasks._birads_rank("4a"))
        self.assertGreater(tasks._birads_rank(3), tasks._birads_rank("??"))


class MammoMaxBiradsTests(_Base):
    modality = "mammo"

    def test_장마다_int_str_섞여도_최댓값을_문자열로(self):
        for i in range(3):
            StorageObject.objects.create(study=self.study, sop_instance_uid=f"1.2.{i}",
                                         orthanc_series_id="s", laterality="left",
                                         view_position="CC")
        outs = iter([
            {"result": {"summary": {"max_birads": 4, "n_lesions": 1}, "lesions": []}},
            {"result": {"summary": {"max_birads": "4c", "n_lesions": 1}, "lesions": []}},
            {"result": {"summary": {"max_birads": "3", "n_lesions": 0}, "lesions": []}},
        ])
        ai = self._ai(None, None, status="running")
        from unittest import mock
        with mock.patch.object(tasks, "_analyze", side_effect=lambda *a, **k: next(outs)):
            out = tasks._mammo(ai, "4b")
        self.assertEqual(out["result"]["summary"]["max_birads"], "4c")
        self.assertEqual(out["result"]["summary"]["n_lesions"], 2)
