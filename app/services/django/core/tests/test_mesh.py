# -*- coding: utf-8 -*-
"""MRI 메시 분리 — 무엇을 걷어내고 무엇을 남기나.

메시 말고는 아무것도 안 걷어내는 것이 이 모듈의 계약이다. 지금 리포트가 안
쓰는 필드도 나중에 필요하고, 빠지면 조용히 망가진다.
"""

import json

from django.test import SimpleTestCase

from core import mesh
from core.api.errors import ApiError


def a_mesh(vertices=3):
    return {"vertices": [[0.0, 1.0, 2.0]] * vertices,
            "triangles": [[0, 1, 2]] * vertices}


def a_response(lesion_count=2, **extra):
    body = {
        "density": {"category": "c", "percent": 41.2,
                    "breast_mesh": a_mesh(5),
                    "dense_tissue_mesh": a_mesh(4)},
        "tumor": {"lesions": [{"index": i, "birads": "4a", "mesh": a_mesh(3)}
                              for i in range(lesion_count)]},
        "grade": {"malignancy": 0.83},
        "meta": {"requested_socket_id": "4", "socket_id": "5"},
    }
    body.update(extra)
    return body


class SplitTests(SimpleTestCase):
    def test_메시_셋이_다_떨어진다(self):
        _, parts = mesh.split(a_response(), 201, 7)
        self.assertEqual([p.kind for p in parts],
                         ["mesh_breast", "mesh_dense",
                          "mesh_lesion", "mesh_lesion"])

    def test_병변마다_하나씩_나온다(self):
        _, parts = mesh.split(a_response(lesion_count=5), 201, 7)
        lesion_parts = [p for p in parts if p.kind == "mesh_lesion"]
        self.assertEqual([p.lesion_index for p in lesion_parts],
                         [0, 1, 2, 3, 4])

    def test_검사_메시는_lesion_index_가_없다(self):
        _, parts = mesh.split(a_response(), 201, 7)
        self.assertIsNone(parts[0].lesion_index)
        self.assertIsNone(parts[1].lesion_index)

    def test_이름에_종류와_판독번호가_들어간다(self):
        # 이름은 한 칸이어야 한다 — Go 가 티켓 접두사(study/201) 뒤에 붙인다.
        # 판독번호가 없으면 같은 검사를 두 번 돌렸을 때 앞의 것을 덮어쓴다.
        _, parts = mesh.split(a_response(), 201, 7)
        for part in parts:
            self.assertNotIn("/", part.object_name)
        self.assertEqual(parts[0].object_name, "mesh_breast-7.json")
        self.assertEqual(parts[3].object_name, "mesh_lesion-1-7.json")

    def test_조영후_몸통_메시도_떨어진다(self):
        # phases=2 (조영 전·후 둘 다 보낸 판독) 에서만 나온다
        body = a_response()
        body["tumor"]["body_mesh"] = a_mesh(9)
        _, parts = mesh.split(body, 201, 7)
        self.assertIn("mesh_body", [p.kind for p in parts])

    def test_바이트와_형식이_실려_나온다(self):
        _, parts = mesh.split(a_response(), 201, 7)
        part = parts[0]
        self.assertEqual(part.bucket, "empatho-derived")
        self.assertEqual(part.content_type, "application/json")
        self.assertEqual(part.byte_size, len(part.payload))
        self.assertEqual(json.loads(part.payload), a_mesh(5))


class StubTests(SimpleTestCase):
    def test_키를_지우지_않고_스텁으로_바꾼다(self):
        stripped, _ = mesh.split(a_response(), 201, 7)
        # 따라 걷는 소비자가 KeyError 를 안 만나야 한다
        self.assertIn("breast_mesh", stripped["density"])
        self.assertTrue(mesh.is_ref(stripped["density"]["breast_mesh"]))

    def test_스텁이_최종_주소를_든다(self):
        # 올리기 전에 이미 맞는 주소여야 한다 — 올린 뒤 고쳐 쓰지 않는다.
        stripped, parts = mesh.split(a_response(), 201, 7)
        ref = stripped["density"]["breast_mesh"][mesh.REF_KEY]
        self.assertEqual(ref["bucket"], parts[0].bucket)
        self.assertEqual(ref["object_key"], "study/201/" + parts[0].object_name)

    def test_스텁에_image_id_는_없다(self):
        # image 행은 업로드 뒤에야 생긴다. (bucket, object_key) 가 조인 키다.
        stripped, _ = mesh.split(a_response(), 201, 7)
        self.assertNotIn("image_id",
                         stripped["density"]["breast_mesh"][mesh.REF_KEY])

    def test_정점_수를_남긴다(self):
        # 소견문이 메시를 안 받고도 「메시 있음」을 말할 수 있어야 한다
        stripped, _ = mesh.split(a_response(), 201, 7)
        ref = stripped["density"]["breast_mesh"][mesh.REF_KEY]
        self.assertEqual(ref["vertex_count"], 5)

    def test_병변_스텁도_제자리에_있다(self):
        stripped, _ = mesh.split(a_response(), 201, 7)
        for lesion in stripped["tumor"]["lesions"]:
            self.assertTrue(mesh.is_ref(lesion["mesh"]))


class KeepEverythingElseTests(SimpleTestCase):
    """메시 외의 필드는 골라내지 않는다."""

    def test_나머지가_글자_그대로_남는다(self):
        stripped, _ = mesh.split(a_response(), 201, 7)
        self.assertEqual(stripped["density"]["category"], "c")
        self.assertEqual(stripped["density"]["percent"], 41.2)
        self.assertEqual(stripped["grade"], {"malignancy": 0.83})
        self.assertEqual(stripped["meta"],
                         {"requested_socket_id": "4", "socket_id": "5"})
        self.assertEqual(stripped["tumor"]["lesions"][0]["birads"], "4a")

    def test_모르는_필드도_남는다(self):
        # 지금 리포트가 안 쓰는 것도 나중에 필요하다
        stripped, _ = mesh.split(
            a_response(future_field={"뭔가": [1, 2, 3]}), 201, 7)
        self.assertEqual(stripped["future_field"], {"뭔가": [1, 2, 3]})

    def test_mesh_로_끝나는_남의_키는_안_건드린다(self):
        # 추측으로 훑지 않는다는 것. 경로가 명시된 둘만 떼어낸다.
        body = a_response()
        body["tumor"]["surface_mesh"] = a_mesh(9)
        stripped, parts = mesh.split(body, 201, 7)
        self.assertEqual(stripped["tumor"]["surface_mesh"], a_mesh(9))
        self.assertEqual(len(parts), 4)

    def test_원본을_안_고친다(self):
        body = a_response()
        mesh.split(body, 201, 7)
        self.assertEqual(body["density"]["breast_mesh"], a_mesh(5))

    def test_메시가_없으면_아무것도_안_한다(self):
        body = {"density": {"category": "a"}, "tumor": {"lesions": []}}
        stripped, parts = mesh.split(body, 201, 7)
        self.assertEqual(parts, [])
        self.assertEqual(stripped, body)

    def test_빈_메시_자리에는_스텁을_안_놓는다(self):
        # 스텁을 놓으면 없는 파일을 가리키게 된다
        body = a_response()
        body["density"]["breast_mesh"] = {}
        body["density"]["dense_tissue_mesh"] = None
        stripped, parts = mesh.split(body, 201, 7)
        self.assertEqual([p.kind for p in parts], ["mesh_lesion"] * 2)
        self.assertEqual(stripped["density"]["breast_mesh"], {})
        self.assertIsNone(stripped["density"]["dense_tissue_mesh"])

    def test_메시가_없는_모달리티도_통과한다(self):
        # 맘모 · 초음파 · 병리 응답에는 density · tumor 자체가 없을 수 있다
        stripped, parts = mesh.split({"birads": "2"}, 201, 7)
        self.assertEqual(parts, [])
        self.assertEqual(stripped, {"birads": "2"})


class GuardTests(SimpleTestCase):
    """메시를 뺐는데도 크면 우리가 모르는 큰 필드가 생긴 것이다."""

    def test_1MB_를_넘으면_저장하지_않는다(self):
        body = a_response()
        body["unknown_huge"] = {"blob": "가" * (mesh.MAX_STORED_BYTES // 2)}
        with self.assertLogs("core.mesh", level="ERROR"):
            with self.assertRaises(ApiError) as caught:
                mesh.split(body, 201, 7)
        self.assertEqual(caught.exception.code, "INTERNAL_ERROR")
        self.assertGreater(caught.exception.details["byte_size"],
                           mesh.MAX_STORED_BYTES)

    def test_메시만_크면_통과한다(self):
        # 이게 정상이다 — 280만 정점이 들어와도 걷어내면 작다
        body = a_response()
        body["density"]["breast_mesh"] = a_mesh(50000)
        stripped, parts = mesh.split(body, 201, 7)
        self.assertLess(len(json.dumps(stripped).encode()),
                        mesh.MAX_STORED_BYTES)
        self.assertGreater(parts[0].byte_size, mesh.MAX_STORED_BYTES)

    def test_응답이_객체가_아니면_막는다(self):
        for bad in ("문자열", [1, 2], None, 7):
            with self.assertRaises(ApiError):
                mesh.split(bad, 201, 7)
