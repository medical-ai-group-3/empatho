"""PersonalNote(todo·스티키·인계 공용) view.

매트릭스(§15)를 안 쓴다 — 부서마다 규칙이 갈리는 자원이 아니다.

  todo · sticky  본인 것만. 남의 메모는 쿼리셋 자체를 owner=request.user 로
                 좁혀서 처리한다 — 존재해도 404 로 본다(403 이 아니다).
  handover       인계 사항. **같은 과(역할) 전체가 보고 지운다** — 교대할 때
                 남기는 게시판이라 본인만 보면 인계가 안 된다(09-27). 다른
                 과 것은 역시 404 다.
"""

from django.db.models import Q
from rest_framework import viewsets, status
from rest_framework.response import Response

from .. import models, serializers
from core.api.permissions import IsAuthenticatedAccount
from core.api.errors import ApiError

SHARED = "handover"


def _visible(account):
    """이 사람이 볼 수 있는 메모 — 자기 것 + 같은 역할의 인계."""
    return models.PersonalNote.objects.filter(
        Q(owner=account) | Q(note_type=SHARED, owner__role=account.role))


class PersonalNoteViewSet(viewsets.ViewSet):
    """GET/POST /me/notes?type=todo|sticky|handover , PATCH/DELETE /me/notes/{id}."""

    permission_classes = [IsAuthenticatedAccount]

    def _get_object(self, request, pk):
        try:
            return _visible(request.user).get(pk=pk)
        except models.PersonalNote.DoesNotExist:
            raise ApiError("NOT_FOUND")

    def list(self, request):
        note_type = request.query_params.get("type")
        qs = (_visible(request.user) if note_type == SHARED
              else models.PersonalNote.objects.filter(owner=request.user))
        if note_type:
            qs = qs.filter(note_type=note_type)
        qs = qs.select_related("owner__staff").order_by("-updated_at")
        out = serializers.PersonalNoteSerializer(qs, many=True)
        return Response(out.data)

    def create(self, request):
        # 종류는 본문이 먼저, 없으면 ?type= 을 본다 — 화면은 주소에 싣는다
        data = {**request.data}
        data.setdefault("note_type", request.query_params.get("type"))
        serializer = serializers.PersonalNoteCreateSerializer(data=data)
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
        # ⚠ **지우는 것은 쓴 사람만.** 완료 처리(PATCH)는 같은 과가 한다 —
        #   교대할 때 남이 넘긴 일을 처리하고 표시하는 것이 인계의 요점이다.
        #   삭제는 다르다. 되돌릴 수 없고, 남의 인계가 사라지면 다음 교대가
        #   그 일이 있었다는 것조차 모른다. 잘못 쓴 사람이 지우면 된다.
        #
        #   404 가 아니라 403 이다 — 같은 과에게는 보이는 메모라, 없다고
        #   하면 거짓말이 된다(todo · sticky 는 애초에 안 보여서 404 다).
        if note.owner_id != request.user.pk:
            raise ApiError("ROLE_FORBIDDEN", "인계는 쓴 사람만 지울 수 있습니다.")
        note.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)
