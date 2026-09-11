# -*- coding: utf-8 -*-
"""에러 카탈로그가 명세 §1-4 와 같은지."""

from django.test import SimpleTestCase

from core.api.errors import ERRORS, INFRA_CODES, SPEC_CODES, ApiError, spec_for

# CDSS_API_명세서_v3 §1-4 표를 손으로 옮긴 것. errors.py 를 고쳐도 이건 안 고친다 —
# 두 벌이 서로를 검사해야 「문서에 있는데 코드에 없다」가 잡힌다.
DOC_CODES_AND_STATUS = {
    "EXAM_PURPOSE_REQUIRED": 422,
    "AI_LOCKED_BEFORE_FIRST_READ": 403,
    "BIRADS3_NOT_ALLOWED_IN_SCREENING": 422,
    "BIRADS3_CONDITION_FAILED": 422,
    "BIRADS_SUBCATEGORY_NOT_FOR_MRI": 422,
    "BINDING_ROLE_FORBIDDEN": 403,
    "SPECIMEN_NOT_BOUND": 409,
    "DISPOSITION_ROLE_ONLY_SURGERY": 403,
    "UNLOCK_ROLE_ONLY_SURGERY": 403,
    "UNLOCK_CONDITION_NOT_MET": 409,
    "REPORT_LOCKED": 409,
    "ASSESSMENT_FINALIZED": 409,
    "STUDY_REJECTED": 409,
    "VALIDATION_ERROR": 400,
    "UNAUTHENTICATED": 401,
    "ROLE_FORBIDDEN": 403,
    "NOT_FOUND": 404,
    "RATE_LIMITED": 429,
    "INFERENCE_FAILED": 500,
    "TICKET_EXPIRED": 401,
    "TICKET_SCOPE_MISMATCH": 403,
    "CHECKSUM_MISMATCH": 409,
    "UPSTREAM_LLM_UNAVAILABLE": 503,
    "PYRAMID_NOT_READY": 409,
    "TILE_OUT_OF_RANGE": 404,
}


class ErrorCatalogTests(SimpleTestCase):
    def test_명세의_25개가_그대로_있다(self):
        self.assertEqual(len(DOC_CODES_AND_STATUS), 25)
        self.assertEqual(SPEC_CODES, set(DOC_CODES_AND_STATUS))

    def test_HTTP_상태가_문서와_같다(self):
        for code, status in DOC_CODES_AND_STATUS.items():
            self.assertEqual(spec_for(code).status, status, code)

    def test_명세_코드와_명세밖_코드가_겹치지_않는다(self):
        self.assertFalse(SPEC_CODES & INFRA_CODES)

    def test_모든_코드에_메시지가_있다(self):
        for code, spec in ERRORS.items():
            self.assertTrue(spec.message.strip(), code)

    def test_카탈로그에_없는_코드는_막힌다(self):
        with self.assertRaises(KeyError):
            ApiError("NOPE_NOT_A_CODE")


class ApiErrorTests(SimpleTestCase):
    def test_코드만으로_상태와_메시지가_붙는다(self):
        exc = ApiError("SPECIMEN_NOT_BOUND")
        self.assertEqual(exc.status_code, 409)
        self.assertEqual(exc.code, "SPECIMEN_NOT_BOUND")
        self.assertIn("연결", exc.message)

    def test_메시지와_details_를_덮어쓸_수_있다(self):
        exc = ApiError("VALIDATION_ERROR", "이러저러", details={"field": "x"})
        self.assertEqual(exc.message, "이러저러")
        self.assertEqual(exc.details, {"field": "x"})
