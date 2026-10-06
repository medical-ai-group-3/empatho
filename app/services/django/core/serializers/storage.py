"""storage_object 공용 serializer — 영상의학과 · 병리과가 함께 쓴다.

부서 전용 파일(radiology.py · pathology.py)에 안 두는 이유 — 취소는 study
소유든 specimen 소유든 같은 규칙(§ views/storage.py 의 StorageObjectCancelView
docstring)이라, 한쪽 부서 파일에 넣으면 다른 쪽이 그걸 import 해야 한다.
"""

from rest_framework import serializers


class StorageObjectCancelSerializer(serializers.Serializer):
    """PATCH /storage-objects/{id}/cancel — 업로드 취소.

    reason 은 선택이다. 비워 보내도 취소 자체는 된다 — 사유를 강제하면
    급하게 잘못 올린 파일 하나 지우는 데도 문구를 짜내야 한다.
    """

    reason = serializers.CharField(max_length=250, required=False, allow_blank=True)
