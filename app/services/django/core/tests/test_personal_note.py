# -*- coding: utf-8 -*-
"""GET/POST /me/notes , PATCH/DELETE /me/notes/{id} — todo·스티키 공용.

본인 것만 CRUD. 남의 메모는 있어도 404(403 이 아니다) — 존재 자체를
노출하지 않는다."""
from django.test import TestCase
from rest_framework.test import APIClient

from core.api.auth import issue_access
from core.models import Account, PersonalNote


def _client_for(account):
    c = APIClient()
    c.credentials(HTTP_AUTHORIZATION="Bearer " + issue_access(account))
    return c


class PersonalNoteTests(TestCase):
    def setUp(self):
        self.account = Account.objects.create(
            login_id="note-owner-test", role="surgery",
            account_status="active", is_active=True,
        )
        self.other_account = Account.objects.create(
            login_id="note-other-test", role="radiology",
            account_status="active", is_active=True,
        )
        self.client = _client_for(self.account)
        self.other_client = _client_for(self.other_account)

    def test_create_todo(self):
        response = self.client.post(
            "/api/v1/me/notes",
            {"note_type": "todo", "content": {"text": "차트 정리", "done": False}},
            format="json",
        )
        self.assertEqual(response.status_code, 201)
        data = response.json()["data"]
        self.assertEqual(data["note_type"], "todo")
        self.assertEqual(data["content"], {"text": "차트 정리", "done": False})
        self.assertEqual(data["owner"], self.account.pk)

    def test_create_sticky(self):
        response = self.client.post(
            "/api/v1/me/notes",
            {"note_type": "sticky", "content": {"text": "회의 3시", "color": "#fef08a"}},
            format="json",
        )
        self.assertEqual(response.status_code, 201)
        data = response.json()["data"]
        self.assertEqual(data["note_type"], "sticky")
        self.assertEqual(data["content"]["color"], "#fef08a")

    def test_list_filters_by_type(self):
        PersonalNote.objects.create(owner=self.account, note_type="todo",
                                    content={"text": "할일1", "done": False})
        PersonalNote.objects.create(owner=self.account, note_type="todo",
                                    content={"text": "할일2", "done": True})
        PersonalNote.objects.create(owner=self.account, note_type="sticky",
                                    content={"text": "메모1", "color": "#fff"})

        todo_response = self.client.get("/api/v1/me/notes?type=todo")
        self.assertEqual(todo_response.status_code, 200)
        self.assertEqual(len(todo_response.json()["data"]), 2)
        self.assertTrue(all(n["note_type"] == "todo" for n in todo_response.json()["data"]))

        sticky_response = self.client.get("/api/v1/me/notes?type=sticky")
        self.assertEqual(len(sticky_response.json()["data"]), 1)
        self.assertEqual(sticky_response.json()["data"][0]["note_type"], "sticky")

        all_response = self.client.get("/api/v1/me/notes")
        self.assertEqual(len(all_response.json()["data"]), 3)

    def test_list_only_shows_own_notes(self):
        mine = PersonalNote.objects.create(owner=self.account, note_type="todo",
                                           content={"text": "내 것", "done": False})
        PersonalNote.objects.create(owner=self.other_account, note_type="todo",
                                    content={"text": "남의 것", "done": False})

        response = self.client.get("/api/v1/me/notes")
        self.assertEqual(response.status_code, 200)
        ids = [n["personal_note_id"] for n in response.json()["data"]]
        self.assertEqual(ids, [mine.pk])

    def test_patch_updates_content(self):
        note = PersonalNote.objects.create(owner=self.account, note_type="todo",
                                           content={"text": "할일", "done": False})
        response = self.client.patch(
            f"/api/v1/me/notes/{note.pk}",
            {"content": {"text": "할일", "done": True}},
            format="json",
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["data"]["content"], {"text": "할일", "done": True})
        note.refresh_from_db()
        self.assertEqual(note.content, {"text": "할일", "done": True})

    def test_delete_removes_note(self):
        note = PersonalNote.objects.create(owner=self.account, note_type="sticky",
                                           content={"text": "지울 것", "color": "#fff"})
        response = self.client.delete(f"/api/v1/me/notes/{note.pk}")
        self.assertEqual(response.status_code, 204)
        self.assertFalse(PersonalNote.objects.filter(pk=note.pk).exists())

    def test_patch_other_users_note_is_404(self):
        other_note = PersonalNote.objects.create(owner=self.other_account, note_type="todo",
                                                  content={"text": "남의 할일", "done": False})
        response = self.client.patch(
            f"/api/v1/me/notes/{other_note.pk}",
            {"content": {"text": "몰래 고치기", "done": True}},
            format="json",
        )
        self.assertEqual(response.status_code, 404)
        other_note.refresh_from_db()
        self.assertEqual(other_note.content, {"text": "남의 할일", "done": False})

    def test_delete_other_users_note_is_404(self):
        other_note = PersonalNote.objects.create(owner=self.other_account, note_type="sticky",
                                                  content={"text": "남의 메모", "color": "#fff"})
        response = self.client.delete(f"/api/v1/me/notes/{other_note.pk}")
        self.assertEqual(response.status_code, 404)
        self.assertTrue(PersonalNote.objects.filter(pk=other_note.pk).exists())

    def test_unauthenticated_is_401(self):
        anon_client = APIClient()
        response = anon_client.get("/api/v1/me/notes")
        self.assertEqual(response.status_code, 401)
