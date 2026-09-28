# -*- coding: utf-8 -*-
"""POST /drugs/dur — 처방 DUR 성분 점검.

원천(식약처 DUR 성분정보)은 부르지 않는다. core.api.dur.fetch 를 갈아
끼우고, 오퍼레이션 · 거르는 칸 · 성분별로 준비한 행을 돌려준다."""
from unittest import mock

from django.core.cache import cache
from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from core.api import dur
from core.api.auth import issue_access
from core.models import Account

URL = "/api/v1/drugs/dur"

COMBO, AGE, PREG, OLD = (dur.OPS[k][0] for k in ("combo", "age", "pregnancy", "elderly"))

# (오퍼레이션, 거르는 값) → 원천이 돌려줄 행들.
ROWS = {
    (COMBO, "아스피린"): [{
        "INGR_KOR_NAME": "아스피린", "MIXTURE_INGR_KOR_NAME": "메토트렉세이트",
        "PROHBT_CONTENT": "혈액학적 독성\n", "REMARK": "methotrexate (1週에 15mg 이상 투여시)",
        "DEL_YN": "정상",
    }],
    (COMBO, "메토트렉세이트"): [{
        "INGR_KOR_NAME": "메토트렉세이트", "MIXTURE_INGR_KOR_NAME": "아스피린리신",
        "PROHBT_CONTENT": "혈액학적 독성\n", "REMARK": "methotrexate (1週에 15mg 이상 투여시)",
        "DEL_YN": "정상",
    }],
    (AGE, "아세트아미노펜"): [{
        "INGR_NAME": "아세트아미노펜", "AGE_BASE": "12세 미만",
        "PROHBT_CONTENT": "과도한 체온강하", "FORM_NAME": "서방정", "DEL_YN": "정상",
    }],
    (AGE, "시메티딘"): [{
        "INGR_NAME": "시메티딘", "AGE_BASE": "24개월 미만",
        "PROHBT_CONTENT": "안전성 미확립", "DEL_YN": "정상",
    }],
    (PREG, "메토트렉세이트"): [{
        "INGR_NAME": "메토트렉세이트", "GRADE": "1등급",
        "PROHBT_CONTENT": "태아 기형", "DEL_YN": "정상",
    }],
    (OLD, "아스피린"): [{
        "INGR_NAME": "아스피린", "PROHBT_CONTENT": None, "DEL_YN": "정상",
    }],
}


def fake_fetch(operation, params):
    name = params.get(dict(dur.OPS.values())[operation])
    rows = ROWS.get((operation, name), [])
    return {"items": [{"item": r} for r in rows], "totalCount": len(rows)}


@override_settings(DUR_API_KEY="test-key")
class DurCheckTests(TestCase):
    def setUp(self):
        cache.clear()
        account = Account.objects.create(
            login_id="dur-test", role="surgery", account_status="active", is_active=True)
        self.client = APIClient()
        self.client.credentials(HTTP_AUTHORIZATION="Bearer " + issue_access(account))
        patcher = mock.patch.object(dur, "fetch", side_effect=fake_fetch)
        self.fetch = patcher.start()
        self.addCleanup(patcher.stop)

    def post(self, body):
        return self.client.post(URL, body, format="json")

    def alerts(self, body, kind=None):
        res = self.post(body)
        self.assertEqual(res.status_code, 200, res.content)
        data = res.json()["data"]
        return data, [a for a in data["alerts"] if kind is None or a["type"] == kind]

    # ── 병용금기 ──
    def test_combo_pair_reported_once_with_salt_match(self):
        # 메토트렉세이트 쪽 행의 짝은 「아스피린리신」— 품는 관계라 아스피린과 같다.
        # 양쪽에서 다 걸려 와도 한 번만 낸다.
        data, combo = self.alerts({"ingredients": ["아스피린", "메토트렉세이트"]}, "combo")
        self.assertEqual(len(combo), 1)
        a = combo[0]
        self.assertEqual(a["level"], "taboo")
        self.assertEqual({a["ingredient"], a["with"]}, {"아스피린", "메토트렉세이트"})
        self.assertIn("혈액학적 독성", a["detail"])
        self.assertIn("15mg", a["detail"])            # 비고를 버리지 않는다
        self.assertEqual(data["checked"], ["아스피린", "메토트렉세이트"])
        self.assertIn("식품의약품안전처", data["source"])
        self.assertIn("처방의", data["disclaimer"])
        self.assertNotIn("partial", data)

    def test_salt_containment_match(self):
        self.assertTrue(dur.match("아스피린리신", "아스피린"))
        self.assertTrue(dur.match("아스피린", "주사용 아스피린리신"))
        self.assertFalse(dur.match("아스피린", "메토트렉세이트"))
        self.assertFalse(dur.match("", "아스피린"))

    def test_combo_needs_the_partner_in_this_prescription(self):
        _, combo = self.alerts({"ingredients": ["아스피린", "아세트아미노펜"]}, "combo")
        self.assertEqual(combo, [])

    # ── 연령 ──
    def test_age_rules_parse(self):
        self.assertEqual(dur.age_rules("18세 이하"), [(18.0, "이하")])
        self.assertEqual(dur.age_rules("24개월 미만"), [(2.0, "미만")])
        self.assertEqual(dur.age_rules("65세 초과"), [(65.0, "초과")])
        self.assertTrue(dur.age_in(18, dur.age_rules("18세 이하")))
        self.assertFalse(dur.age_in(18, dur.age_rules("18세 미만")))
        self.assertTrue(dur.age_in(1, dur.age_rules("24개월 미만")))
        self.assertFalse(dur.age_in(2, dur.age_rules("24개월 미만")))
        self.assertTrue(dur.age_in(66, dur.age_rules("65세 이상")))
        self.assertTrue(dur.age_in(5, dur.age_rules("3세 이상 12세 미만")))
        self.assertFalse(dur.age_in(2, dur.age_rules("3세 이상 12세 미만")))

    def test_age_taboo_applied_only_in_range(self):
        _, age = self.alerts({"ingredients": ["아세트아미노펜", "시메티딘"], "age": 1}, "age")
        self.assertEqual({a["ingredient"] for a in age}, {"아세트아미노펜", "시메티딘"})
        self.assertTrue(all(a["level"] == "taboo" for a in age))
        self.assertIn("서방정", age[0]["detail"] + age[1]["detail"])   # 제형 조건을 싣는다

        _, age = self.alerts({"ingredients": ["아세트아미노펜", "시메티딘"], "age": 30}, "age")
        self.assertEqual(age, [])

    def test_age_unknown_skips_age_and_elderly_calls(self):
        data, _ = self.alerts({"ingredients": ["아세트아미노펜"]})
        self.assertEqual(data["ran"], ["combo"])
        called = {c.args[0] for c in self.fetch.call_args_list}
        self.assertEqual(called, {COMBO})

    # ── 임부 ──
    def test_pregnancy_caution_only_for_fertile_female(self):
        _, preg = self.alerts({"ingredients": ["메토트렉세이트"], "age": 30, "sex": "F"},
                              "pregnancy")
        self.assertEqual(len(preg), 1)
        self.assertEqual(preg[0]["level"], "caution")
        self.assertIn("1등급", preg[0]["message"])
        self.assertIn("임신 가능성", preg[0]["message"])

        # 나이를 모르는 여성도 본다.
        _, preg = self.alerts({"ingredients": ["메토트렉세이트"], "sex": "F"}, "pregnancy")
        self.assertEqual(len(preg), 1)

        for body in ({"age": 30, "sex": "M"}, {"age": 51, "sex": "F"},
                     {"age": 14, "sex": "F"}, {"age": 30}):
            _, preg = self.alerts({"ingredients": ["메토트렉세이트"], **body}, "pregnancy")
            self.assertEqual(preg, [], body)

    # ── 노인 ──
    def test_elderly_caution_from_65(self):
        _, old = self.alerts({"ingredients": ["아스피린"], "age": 65}, "elderly")
        self.assertEqual(len(old), 1)
        self.assertEqual(old[0]["level"], "caution")
        _, old = self.alerts({"ingredients": ["아스피린"], "age": 64}, "elderly")
        self.assertEqual(old, [])

    def test_taboo_sorted_before_caution(self):
        data, _ = self.alerts({"ingredients": ["아스피린", "메토트렉세이트"],
                               "age": 66, "sex": "F"})
        levels = [a["level"] for a in data["alerts"]]
        self.assertEqual(levels, sorted(levels, key=lambda l: l != "taboo"))
        self.assertEqual(data["ran"], ["combo", "age", "elderly"])

    # ── 실패 ──
    @override_settings(DUR_API_KEY="")
    def test_empty_key_is_503(self):
        res = self.post({"ingredients": ["아스피린"]})
        self.assertEqual(res.status_code, 503)
        self.assertEqual(res.json()["error"]["code"], "UPSTREAM_DUR_UNAVAILABLE")
        self.fetch.assert_not_called()

    def test_one_op_failing_is_partial(self):
        def flaky(operation, params):
            if operation == OLD:
                raise dur.UpstreamFailed(operation)
            return fake_fetch(operation, params)
        self.fetch.side_effect = flaky

        data, _ = self.alerts({"ingredients": ["아스피린", "메토트렉세이트"], "age": 70})
        self.assertTrue(data["partial"])
        self.assertEqual(data["failed"], ["elderly"])
        self.assertEqual(len([a for a in data["alerts"] if a["type"] == "combo"]), 1)

    def test_failure_is_not_cached(self):
        self.fetch.side_effect = dur.UpstreamFailed(COMBO)
        data, _ = self.alerts({"ingredients": ["아스피린", "메토트렉세이트"]})
        self.assertEqual(data["failed"], ["combo"])
        self.fetch.side_effect = fake_fetch
        data, combo = self.alerts({"ingredients": ["아스피린", "메토트렉세이트"]}, "combo")
        self.assertEqual(len(combo), 1)
        self.assertNotIn("partial", data)

    def test_results_are_cached(self):
        self.alerts({"ingredients": ["아스피린"]})
        self.alerts({"ingredients": [" 아스피린 "]})
        self.assertEqual(self.fetch.call_count, 1)

    def test_upstream_items_shapes(self):
        row = {"INGR_NAME": "x"}
        self.assertEqual(dur.rows_of({"items": [{"item": row}]}), [row])
        self.assertEqual(dur.rows_of({"items": {"item": [row]}}), [row])
        self.assertEqual(dur.rows_of({"items": {"item": row}}), [row])
        self.assertEqual(dur.rows_of({"items": ""}), [])
        self.assertEqual(dur.rows_of({}), [])

    # ── 검증 ──
    def test_validation(self):
        for body in ({}, {"ingredients": []}, {"ingredients": ["", "  "]},
                     {"ingredients": "아스피린"},
                     {"ingredients": ["약%d" % i for i in range(21)]},
                     {"ingredients": ["아스피린"], "age": "66"},
                     {"ingredients": ["아스피린"], "age": -1},
                     {"ingredients": ["아스피린"], "age": True},
                     {"ingredients": ["아스피린"], "sex": "female"},
                     {"ingredients": ["아스피린"], "patient_id": 1}):
            res = self.post(body)
            self.assertEqual(res.status_code, 400, body)
            self.assertEqual(res.json()["error"]["code"], "VALIDATION_ERROR", body)
        self.fetch.assert_not_called()

    def test_blank_and_duplicate_ingredients_dropped(self):
        data, _ = self.alerts({"ingredients": ["아스피린", "", " 아스피린 ", None]})
        self.assertEqual(data["checked"], ["아스피린"])

    def test_requires_login(self):
        res = APIClient().post(URL, {"ingredients": ["아스피린"]}, format="json")
        self.assertEqual(res.status_code, 401)

    def test_route_is_not_captured_by_drug_detail(self):
        # drugs/<str:item_seq> 보다 앞에 있어야 한다 — 뒤면 405 다.
        res = self.post({"ingredients": ["아스피린"]})
        self.assertEqual(res.status_code, 200)
