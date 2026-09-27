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

    def test_같은_과가_지울_수_있다(self):
        note = models.PersonalNote.objects.create(owner=self.a, note_type="handover",
                                                  content={"text": "x"})
        self._as(self.b)
        self.assertEqual(self.client.delete(f"/api/v1/me/notes/{note.pk}").status_code, 204)

    def test_할_일은_여전히_본인만(self):
        models.PersonalNote.objects.create(owner=self.a, note_type="todo", content={"text": "내 것"})
        self.assertEqual(self._list(self.b, "todo"), [])
