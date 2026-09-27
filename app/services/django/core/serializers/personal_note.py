"""PersonalNote(todo·스티키 공용) serializer — 개인 전용, 부서 무관이라
다른 부서 serializer 파일에 안 둔다."""

from rest_framework import serializers

from .. import models


class PersonalNoteSerializer(serializers.ModelSerializer):
    # 인계는 같은 과가 같이 본다 — 누가 남겼는지가 있어야 읽힌다
    owner_name = serializers.SerializerMethodField()

    def get_owner_name(self, note):
        staff = getattr(note.owner, "staff", None)
        return getattr(staff, "full_name", None) or note.owner.login_id

    class Meta:
        model = models.PersonalNote
        fields = "__all__"


class PersonalNoteCreateSerializer(serializers.Serializer):
    """POST /me/notes."""

    note_type = serializers.ChoiceField(choices=models.as_choices(models.NOTE_TYPE))
    content = serializers.JSONField(required=False)


class PersonalNoteUpdateSerializer(serializers.Serializer):
    """PATCH /me/notes/{id} — content 만 바꾼다. 완결적으로 통째로 덮어쓴다
    (부분 병합이 아니다) — todo 는 {text,done}, sticky 는 {text,color} 라
    칸이 몇 개 안 돼서 화면이 항상 전체를 다시 보낸다."""

    content = serializers.JSONField()
