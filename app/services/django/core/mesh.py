# -*- coding: utf-8 -*-
"""MRI 3D 메시를 응답에서 걷어내 Garage 로 보낸다.

MRI 응답이 24~33MB 인데 99.98% 가 메시다 — 정점·삼각형 좌표가 한 응답에 280만
개 들어 있다. 메시를 빼면 4.3KB 고, 나머지 모달리티는 전부 7KB 미만이다.
그대로 ai_result.result 에 넣으면 jsonb 한 칸이 30MB 가 된다.

    응답 ──split()──▶ result 에 넣을 JSON (4.3KB)
                  └─▶ 메시 조각들 ──티켓──▶ Go ──▶ Garage ──I-1──▶ image 행

**메시 말고는 아무것도 걷어내지 않는다.** 지금 리포트가 안 쓰는 필드도 나중에
필요하고, 빠지면 조용히 망가진다. 그래서 경로를 명시하고 추측하지 않는다 —
`_mesh` 로 끝나는 키를 훑거나 「배열이 크면」 같은 규칙을 쓰면 언젠가 메시가
아닌 것을 지운다.

대신 걷어낸 뒤 크기를 재서 1MB 를 넘으면 저장하지 않고 터뜨린다. 추론이 메시
필드를 하나 더 늘리면 30MB 행이 조용히 들어가는 대신 여기서 걸린다.
"""

import copy
import json
import logging

from .api.errors import ApiError
from .api.tickets import object_key_prefix

logger = logging.getLogger(__name__)

#: 검사당 1개인 메시. (image.kind, 응답에서의 경로)
#: 경로는 판독값(응답의 result) 기준이다 — split() 에 봉투가 아니라 그 안쪽을 넘긴다.
#: body_mesh 는 조영 후 볼륨까지 보낸 판독(phases=2)에서만 나온다. 조영 전만
#: 보내면 tumor 자체가 null 이라 아래 세 줄 중 셋째와 병변 메시가 없다.
STUDY_MESHES = (
    ("mesh_breast", ("density", "breast_mesh")),
    ("mesh_dense", ("density", "dense_tissue_mesh")),
    ("mesh_body", ("tumor", "body_mesh")),
)

#: 병변당 1개인 메시. 이 배열의 원소마다 "mesh" 키를 본다.
LESION_ARRAY = ("tumor", "lesions")
LESION_MESH_KEY = "mesh"
LESION_KIND = "mesh_lesion"

#: 메시를 뺀 JSON 의 상한. 넘으면 우리가 모르는 큰 필드가 새로 생긴 것이다.
MAX_STORED_BYTES = 1 * 1024 ** 2

#: 좌표 배열 JSON 을 그대로 올린다. 추론팀의 glTF/Draco 계획은 확인 중이다.
CONTENT_TYPE = "application/json"
DERIVED_BUCKET = "empatho-derived"

#: 스텁을 알아보는 키. 이 키가 있으면 「메시가 있었고 저기 있다」는 뜻이다.
REF_KEY = "$mesh_ref"


class MeshPart:
    """떼어낸 메시 하나. Garage 로 보낼 바이트와 그 주소를 든다."""

    __slots__ = ("kind", "lesion_index", "object_name", "payload",
                 "byte_size", "vertex_count")

    def __init__(self, kind, lesion_index, object_name, payload, vertex_count):
        self.kind = kind
        self.lesion_index = lesion_index      # mesh_lesion 이 아니면 None
        self.object_name = object_name
        self.payload = payload
        self.byte_size = len(payload)
        self.vertex_count = vertex_count
        

    @property
    def bucket(self):
        return DERIVED_BUCKET

    @property
    def content_type(self):
        return CONTENT_TYPE

    def __repr__(self):
        return "<MeshPart %s %s %dB>" % (self.kind, self.object_name,
                                         self.byte_size)


def split(response, study_id, ai_result_id):
    """(저장할 JSON, 떼어낸 메시 목록) 으로 가른다.

    원본은 건드리지 않는다. 메시가 있던 자리에는 키를 지우지 않고 스텁을 넣는다 —
    density.breast_mesh 를 따라 걷는 소비자가 KeyError 대신 「여기 있었고 저기
    있다」를 보게 하려는 것이다.

    스텁은 image_id 가 아니라 (bucket, object_key) 를 든다. image 행은 업로드
    뒤에야 생기는데 그 주소는 지금 정할 수 있어서, JSON 을 두 번 쓰지 않아도
    된다. image 에 (bucket, object_key) UNIQUE 가 걸려 있어 그 쌍이 곧 조인 키다.
    """
    if not isinstance(response, dict):
        raise ApiError("VALIDATION_ERROR", "추론 응답이 객체가 아닙니다.",
                       details={"type": type(response).__name__})

    stripped = copy.deepcopy(response)
    parts = []
    prefix = object_key_prefix("study", study_id)
    # 이름은 한 칸이어야 한다 — Go 가 티켓 접두사(study/<id>) 뒤에 붙인다.
    # 판독 번호를 넣어 같은 검사의 다른 실행과 구분한다.
    for kind, path in STUDY_MESHES:
        part = _take(stripped, path, kind, None,
                     "%s-%s.json" % (kind, ai_result_id), prefix)
        if part is not None:
            parts.append(part)

    lesions = _dig(stripped, LESION_ARRAY)
    if isinstance(lesions, list):
        for index, lesion in enumerate(lesions):
            if not isinstance(lesion, dict):
                continue
            part = _take(lesion, (LESION_MESH_KEY,), LESION_KIND, index,
                         "%s-%d-%s.json" % (LESION_KIND, index, ai_result_id),
                         prefix)
            if part is not None:
                parts.append(part)

    _guard(stripped, study_id, parts)
    return stripped, parts


def _take(node, path, kind, lesion_index, object_name, prefix):
    """path 의 메시를 떼어내고 그 자리에 스텁을 놓는다. 없으면 None."""
    parent = _dig(node, path[:-1])
    key = path[-1]
    if not isinstance(parent, dict):
        return None

    mesh = parent.get(key)
    # None 이나 빈 것은 「메시를 안 냈다」다. 스텁을 놓으면 없는 파일을 가리킨다.
    if not isinstance(mesh, dict) or not mesh:
        return None

    payload = json.dumps(mesh, ensure_ascii=False,
                         separators=(",", ":")).encode()
    part = MeshPart(kind, lesion_index, object_name, payload,
                    _vertex_count(mesh))
    parent[key] = {REF_KEY: {"bucket": part.bucket,
                             "object_key": "%s/%s" % (prefix, part.object_name),
                             "content_type": part.content_type,
                             "byte_size": part.byte_size,
                             "vertex_count": part.vertex_count}}
    return part


def _dig(node, path):
    for key in path:
        if not isinstance(node, dict):
            return None
        node = node.get(key)
    return node


def _vertex_count(mesh):
    """소견문이 메시를 안 받고도 「메시 있음」을 말할 수 있게 남긴다.

    모델이 vertex_count 를 직접 넣어 준다(09-16 확인). 좌표 배열의 키는
    vertices 가 아니라 positions 라서, 그 이름으로 세면 늘 None 이 된다.
    """
    counted = mesh.get("vertex_count")
    if isinstance(counted, int):
        return counted
    for key in ("positions", "vertices"):
        value = mesh.get(key)
        if isinstance(value, list):
            return len(value)
    return None


def _guard(stripped, study_id, parts):
    size = len(json.dumps(stripped, ensure_ascii=False,
                          separators=(",", ":")).encode())
    if size <= MAX_STORED_BYTES:
        return
    logger.error("[mesh] 걷어낸 뒤에도 %dB 다 study=%s 메시=%d개 — "
                 "우리가 모르는 큰 필드가 생겼다", size, study_id, len(parts))
    raise ApiError("INTERNAL_ERROR", "추론 응답이 저장 상한을 넘었습니다.",
                   details={"byte_size": size, "limit": MAX_STORED_BYTES,
                            "mesh_count": len(parts)})


def is_ref(value):
    """스텁인가. 리포트가 메시 자리를 만났을 때 쓴다."""
    return isinstance(value, dict) and REF_KEY in value
