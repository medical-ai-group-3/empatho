"""PersonalNote(todo·스티키 공용) view — 개인 전용, 부서 무관.

매트릭스(§15)를 안 쓴다 — 부서마다 규칙이 갈리는 자원이 아니라 "본인 것만"
하나뿐이라 IsAuthenticatedAccount 로 충분하다. 남의 메모는 쿼리셋 자체를
owner=request.user 로 좁혀서 처리한다 — 존재해도 404 로 본다(403 이
아니다). 있는지조차 알려주지 않는다(요청에 있던 조건 그대로).
"""

from rest_framework import viewsets, status
from rest_framework.response import Response

from .. import models, serializers
from core.api.permissions import IsAuthenticatedAccount
from core.api.errors import ApiError


class PersonalNoteViewSet(viewsets.ViewSet):
    """GET/POST /me/notes?type=todo|sticky , PATCH/DELETE /me/notes/{id}."""

    permission_classes = [IsAuthenticatedAccount]

    def _get_object(self, request, pk):
        try:
            return models.PersonalNote.objects.get(pk=pk, owner=request.user)
        except models.PersonalNote.DoesNotExist:
            raise ApiError("NOT_FOUND")

    def list(self, request):
        qs = models.PersonalNote.objects.filter(owner=request.user)
        note_type = request.query_params.get("type")
        if note_type:
            qs = qs.filter(note_type=note_type)
        qs = qs.order_by("-updated_at")
        out = serializers.PersonalNoteSerializer(qs, many=True)
        return Response(out.data)

    def create(self, request):
        serializer = serializers.PersonalNoteCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        note = models.PersonalNote.objects.create(
            owner=request.user,
            note_type=data["note_type"],
            content=data.get("content"),
        )
        out = serializers.PersonalNoteSerializer(note)
        return Response(out.data, status=status.HTTP_201_CREATED)

    def partial_update(self, request, pk=None):
        note = self._get_object(request, pk)
        serializer = serializers.PersonalNoteUpdateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        note.content = serializer.validated_data["content"]
        note.save()

        out = serializers.PersonalNoteSerializer(note)
        return Response(out.data)

    def destroy(self, request, pk=None):
        note = self._get_object(request, pk)
        note.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)
