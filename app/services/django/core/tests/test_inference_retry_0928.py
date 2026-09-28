# -*- coding: utf-8 -*-
"""추론 서버가 잠깐 못 받은 것만 다시 건다 (09-28).

    GPU 메모리 부족(predict_failed · OutOfMemoryError) 기권과 HTTP 5xx 는
    Celery retry 로 두 번(20초 · 60초 뒤) 더 건다. 그동안 행은 queued 다.
    마지막 시도에서도 안 되면 예전과 똑같이 남긴다 — 사유는 그대로.
    그 밖의 기권 · 실패는 다시 걸지 않는다.

    HTTP 는 urllib.request.urlopen 을 가로챈다 — Go(파일) · 추론 서버 둘 다.
    요청 계약(주소 · multipart 칸)은 바꾸지 않았으므로 주소만 보고 가른다.
"""
import io
import json
import urllib.error
from datetime import date
from unittest import mock

from django.test import TestCase
from rest_framework.test import APIClient

from core import tasks
from core.api.auth import issue_access
from core.models import (Account, AiResult, ExamOrder, Patient, PatientPii,
                         Staff, StorageObject, Study)

OOM = ("predict_failed: OutOfMemoryError: CUDA out of memory. Tried to allocate 1.60 GiB. "
       "GPU 0 has a total capacity of 31.36 GiB of which 1.43 GiB is free.")


class _Resp(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _ok(n_lesions=1):
    return {"abstained": False, "result": {
        "summary": {"abstained": False, "n_lesions": n_lesions, "max_birads": "4a", "biopsy": True},
        "lesions": [{"id": "m1", "box": [1, 2, 3, 4], "birads": "4a"}]}}


def _oom():
    return {"abstained": True, "reason": OOM}


class _Fake:
    """urlopen 대역. 추론 서버 응답을 차례로 꺼낸다. dict 는 JSON, 예외는 던진다."""

    def __init__(self, answers):
        self.answers = list(answers)
        self.inference_calls = []

    def __call__(self, req, timeout=None):
        url = req.full_url if hasattr(req, "full_url") else str(req)
        if url.startswith(tasks.GATEWAY):
            return _Resp(b"DICM-bytes")
        self.inference_calls.append(url)
        a = self.answers.pop(0)
        if isinstance(a, Exception):
            raise a
        return _Resp(json.dumps(a).encode())


def _http(code):
    return urllib.error.HTTPError(f"{tasks.INFERENCE}/analyze/4b", code, "err", {}, io.BytesIO(b""))


class InferenceRetryTests(TestCase):
    def setUp(self):
        self.account = Account.objects.create(
            login_id="rad-retry", role="radiology", account_status="active", is_active=True)
        Staff.objects.create(account=self.account, staff_number="RAD-RETRY", full_name="재시도")
        self.patient = Patient.objects.create(patient_number="P-RETRY")
        PatientPii.objects.create(patient=self.patient, name="재시도환자",
                                  birth_date=date(1980, 1, 1), phone="010-0000-0000")

    def _study(self, modality, n=1):
        order = ExamOrder.objects.create(
            patient=self.patient, order_status="ordered", modality=modality,
            exam_purpose="diagnostic", ordered_by=self.account.staff)
        study = Study.objects.create(patient=self.patient, exam_order=order, modality=modality)
        objs = []
        for i, (lat, view) in enumerate([("right", "CC"), ("right", "MLO"), ("left", "CC"), ("left", "MLO")][:n]):
            if modality == "mammo":
                objs.append(StorageObject.objects.create(
                    study=study, sop_instance_uid=f"1.2.3.{i}", orthanc_series_id="s",
                    laterality=lat, view_position=view))
            else:
                objs.append(StorageObject.objects.create(
                    study=study, bucket="empatho-original",
                    object_key=f"study/{study.pk}/img{i}.png"))
        return study, objs

    def _ai(self, study, source=None):
        return AiResult.objects.create(patient=self.patient, study=study,
                                       source_object=source, run_status="queued")

    def _run(self, ai, fake):
        """eager 로 돌린다 — Celery 가 retry 를 그 자리에서 다시 돌려 준다(countdown 은
        기다리지 않는다). 뒤처리(병변 · 리포트)와 sleep 은 막는다.
        돌려주는 값: (결과, [(countdown, 그때 행 상태)…])"""
        waits = []
        task_cls = type(tasks.run_inference._get_current_object())   # shared_task 는 Proxy 다
        orig = task_cls.retry

        def spy(task, *a, **k):
            waits.append((k.get("countdown"), AiResult.objects.get(pk=ai.pk).run_status))
            return orig(task, *a, **k)

        with mock.patch("core.tasks.urllib.request.urlopen", side_effect=fake),              mock.patch("core.tasks.issue", return_value=("tok", None, None)),              mock.patch("core.tasks.time.sleep"),              mock.patch.object(tasks, "_store_lesions"),              mock.patch("core.reports.issue_stage_report"),              mock.patch("core.tasks._store_lesion_meshes"),              mock.patch.object(task_cls, "retry", autospec=True, side_effect=spy):
            res = tasks.run_inference.apply(args=(ai.pk,))
        ai.refresh_from_db()
        return res.result, waits

    # ── 감별 ───────────────────────────────────────────────────
    def test_oom_사유만_골라낸다(self):
        self.assertEqual(tasks._oom_reason(_oom()), OOM)
        self.assertIsNone(tasks._oom_reason({"abstained": True, "reason": "no_detection"}))
        self.assertIsNone(tasks._oom_reason(_ok()))
        self.assertTrue(tasks._transient(tasks.InferenceBusy(OOM)))
        self.assertTrue(tasks._transient(_http(503)))
        self.assertFalse(tasks._transient(_http(400)))
        self.assertFalse(tasks._transient(ValueError("x")))

    # ── 맘모 GPU 메모리 부족 → 다시 → 성공 ──────────────────────
    def test_mammo_oom_이면_20초_뒤_넷을_다시_걸어_성공(self):
        study, _ = self._study("mammo", n=4)
        ai = self._ai(study)
        # 둘째 장에서 메모리 부족 — 넷을 통째로 다시 건다
        fake = _Fake([_ok(), _oom()] + [_ok()] * 4)
        result, waits = self._run(ai, fake)
        self.assertEqual(result, "done")
        self.assertEqual(waits, [(20, "queued")])   # 기다리는 동안 화면은 queued 를 본다
        self.assertEqual(len(fake.inference_calls), 6)
        self.assertEqual(ai.run_status, "done")
        self.assertFalse(ai.abstained)
        self.assertIsNone(ai.abstain_reason)
        self.assertEqual(ai.result["result"]["summary"]["n_lesions"], 4)

    def test_세_번_다_oom_이면_20_60_뒤_예전처럼_기권_사유_그대로(self):
        study, _ = self._study("mammo", n=1)
        ai = self._ai(study)
        fake = _Fake([_oom(), _oom(), _oom()])
        result, waits = self._run(ai, fake)
        self.assertEqual(result, "done")
        self.assertEqual([w for w, _ in waits], [20, 60])
        self.assertEqual(len(fake.inference_calls), 1 + len(tasks.RETRY_COUNTDOWNS))
        self.assertEqual(ai.run_status, "done")
        self.assertTrue(ai.abstained)
        self.assertEqual(ai.abstain_reason, OOM)

    # ── 초음파(단일 _analyze) · 5xx ───────────────────────────
    def test_us_oom_도_다시_건다(self):
        study, objs = self._study("us", n=1)
        ai = self._ai(study, objs[0])
        fake = _Fake([_oom(), _oom(), _oom()])
        result, waits = self._run(ai, fake)
        self.assertEqual([w for w, _ in waits], [20, 60])
        self.assertEqual(ai.abstain_reason, OOM)

    def test_5xx_는_다시_건다_마지막엔_failed_사유_그대로(self):
        study, objs = self._study("us", n=1)
        ai = self._ai(study, objs[0])
        # 시도마다 _analyze 안에서 한 번 더 건다(연결 끊김 대비) — 그래서 두 번씩
        fake = _Fake([_http(503)] * 6)
        result, waits = self._run(ai, fake)
        self.assertEqual(result, "failed")
        self.assertEqual([w for w, _ in waits], [20, 60])
        self.assertEqual(len(fake.inference_calls), 6)
        self.assertEqual(ai.run_status, "failed")
        self.assertTrue(ai.abstain_reason.startswith("HTTPError:"))
        self.assertIn("503", ai.abstain_reason)

    def test_5xx_뒤_성공(self):
        study, _ = self._study("mammo", n=1)
        ai = self._ai(study)
        fake = _Fake([_http(502), _http(502), _ok()])
        result, waits = self._run(ai, fake)
        self.assertEqual(result, "done")
        self.assertEqual([w for w, _ in waits], [20])
        self.assertFalse(ai.abstained)

    # ── 다시 걸지 않는 것 ──────────────────────────────────────
    def test_모델_기권은_다시_걸지_않는다(self):
        study, _ = self._study("mammo", n=1)
        ai = self._ai(study)
        fake = _Fake([{"abstained": True, "reason": "no_detection"}])
        result, waits = self._run(ai, fake)
        self.assertEqual(result, "done")
        self.assertEqual(waits, [])
        self.assertTrue(ai.abstained)
        self.assertEqual(ai.abstain_reason, "no_detection")
        self.assertEqual(len(fake.inference_calls), 1)

    def test_4xx_는_다시_걸지_않는다(self):
        study, objs = self._study("us", n=1)
        ai = self._ai(study, objs[0])
        result, waits = self._run(ai, _Fake([_http(422), _http(422)]))
        self.assertEqual(result, "failed")
        self.assertEqual(waits, [])

    def test_요청_계약은_그대로_소켓_주소(self):
        study, _ = self._study("mammo", n=1)
        ai = self._ai(study)
        fake = _Fake([_ok()])
        self._run(ai, fake)
        self.assertEqual(fake.inference_calls, [f"{tasks.INFERENCE}/analyze/4b"])


class ProgressLatestRowTests(TestCase):
    """GET /ai-results?study= 는 대상마다 가장 최근 행으로 센다 — 다시 돌린 판독이
    지난번 failed 행 때문에 failed 로 보이지 않게."""

    def setUp(self):
        self.account = Account.objects.create(
            login_id="rad-prog", role="radiology", account_status="active", is_active=True)
        Staff.objects.create(account=self.account, staff_number="RAD-PROG", full_name="진행")
        self.patient = Patient.objects.create(patient_number="P-PROG")
        order = ExamOrder.objects.create(
            patient=self.patient, order_status="ordered", modality="mammo",
            exam_purpose="diagnostic", ordered_by=self.account.staff)
        self.study = Study.objects.create(patient=self.patient, exam_order=order, modality="mammo")
        self.client = APIClient()
        self.client.credentials(HTTP_AUTHORIZATION="Bearer " + issue_access(self.account))

    def _prog(self):
        r = self.client.get(f"/api/v1/ai-results?study={self.study.pk}")
        self.assertEqual(r.status_code, 200, r.content)
        body = r.json()
        return body.get("data", body)

    def test_지난_failed_뒤_새_행이_돌면_running(self):
        AiResult.objects.create(patient=self.patient, study=self.study, run_status="failed")
        AiResult.objects.create(patient=self.patient, study=self.study, run_status="running")
        self.assertEqual(self._prog()["status"], "running")

    def test_새_행이_끝나면_done(self):
        AiResult.objects.create(patient=self.patient, study=self.study, run_status="failed")
        AiResult.objects.create(patient=self.patient, study=self.study, run_status="done")
        p = self._prog()
        self.assertEqual(p["status"], "done")
        self.assertEqual(p["pct"], 100)
        self.assertEqual(len(p["results"]), 2)   # 목록은 예전처럼 전부

    def test_최근_행이_failed_면_failed(self):
        AiResult.objects.create(patient=self.patient, study=self.study, run_status="done")
        AiResult.objects.create(patient=self.patient, study=self.study, run_status="failed")
        self.assertEqual(self._prog()["status"], "failed")
