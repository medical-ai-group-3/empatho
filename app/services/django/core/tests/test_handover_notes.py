"""인계 사항 — 같은 과는 같이 보고 지우고, 다른 과 · 남의 할 일은 못 본다."""
from rest_framework.test import APITestCase

from core import models
from core.api.auth import issue_access


def _account(login, role):
    return models.Account.objects.create(login_id=login, role=role,
                                         account_status="active", is_active=True)


class HandoverNoteTests(APITestCase):
    def setUp(self):
        self.a = _account("path_a", "pathology")
        self.b = _account("path_b", "pathology")
        self.r = _account("rad_a", "radiology")

    def _as(self, acc):
        self.client.credentials(HTTP_AUTHORIZATION="Bearer " + issue_access(acc))

    def _list(self, acc, kind):
        self._as(acc)
        return [n["content"]["text"] for n in
                self.client.get(f"/api/v1/me/notes?type={kind}").json()["data"]]

    def test_같은_과는_보고_다른_과는_못_본다(self):
        self._as(self.a)
        r = self.client.post("/api/v1/me/notes?type=handover",
                             {"content": {"text": "슬라이드 재염색"}}, format="json")
        self.assertEqual(r.status_code, 201)
        self.assertEqual(self._list(self.b, "handover"), ["슬라이드 재염색"])
        self.assertEqual(self._list(self.r, "handover"), [])

    def test_같은_과는_완료_처리를_할_수_있다(self):
        """교대할 때 남이 넘긴 일을 처리하고 표시하는 것이 인계의 요점이다."""
        note = models.PersonalNote.objects.create(owner=self.a, note_type="handover",
                                                  content={"text": "x"})
        self._as(self.b)
        r = self.client.patch(f"/api/v1/me/notes/{note.pk}",
                              {"content": {"text": "x", "done": True,
                                           "done_by": "박병리"}}, format="json")

        self.assertEqual(r.status_code, 200)
        note.refresh_from_db()
        self.assertTrue(note.content["done"])

    def test_남의_인계는_못_지운다(self):
        """삭제는 되돌릴 수 없다 — 남의 인계가 사라지면 다음 교대가 그 일이
        있었다는 것조차 모른다. 처리했으면 완료로 표시한다."""
        note = models.PersonalNote.objects.create(owner=self.a, note_type="handover",
                                                  content={"text": "x"})
        self._as(self.b)

        self.assertEqual(self.client.delete(f"/api/v1/me/notes/{note.pk}").status_code, 403)
        self.assertTrue(models.PersonalNote.objects.filter(pk=note.pk).exists())

    def test_쓴_사람은_지울_수_있다(self):
        note = models.PersonalNote.objects.create(owner=self.a, note_type="handover",
                                                  content={"text": "x"})
        self._as(self.a)

        self.assertEqual(self.client.delete(f"/api/v1/me/notes/{note.pk}").status_code, 204)

    def test_다른_과는_보이지도_지워지지도_않는다(self):
        note = models.PersonalNote.objects.create(owner=self.a, note_type="handover",
                                                  content={"text": "x"})
        self._as(self.r)

        self.assertEqual(self.client.delete(f"/api/v1/me/notes/{note.pk}").status_code, 404)

    def test_누가_썼는지_번호로_내려준다(self):
        """화면이 「내가 쓴 것」을 가른다 — 이름은 동명이인에서 틀린다."""
        staff = models.Staff.objects.create(account=self.a, full_name="김병리",
                                            staff_number="S-PATH-1")
        models.PersonalNote.objects.create(owner=self.a, note_type="handover",
                                           content={"text": "x"})
        self._as(self.b)

        row = self.client.get("/api/v1/me/notes?type=handover").json()["data"][0]
        self.assertEqual(row["owner_staff_id"], staff.staff_id)
        self.assertEqual(row["owner_name"], "김병리")

    def test_할_일은_여전히_본인만(self):
        models.PersonalNote.objects.create(owner=self.a, note_type="todo", content={"text": "내 것"})
        self.assertEqual(self._list(self.b, "todo"), [])
