"""역할(account.role) 기반 권한.

인증은 아직 없다(라우터 인계 문서: 데이터 API 우선, /login·/signup 나중).
지금은 요청에서 역할을 어떻게 꺼낼지만 한 곳에 모아두고, 실제 차단은
_resolve_role() 이 실제 계정을 반환하게 되는 시점에 켠다.
"""

from rest_framework.permissions import BasePermission

# account.role enum — models.ROLE 과 같아야 한다.
ROLES = {"admin", "reception", "nursing", "radiology", "surgery", "pathology", "patient"}


def resolve_role(request):
    """현재 요청자의 역할 문자열. 없으면 None.

    TODO(auth): 세션 인증이 붙으면 request.user 와 이어진 account.role 을 반환.
    당분간은 개발 편의로 X-Debug-Role 헤더를 읽는다(운영에서는 제거).
    """
    return request.headers.get("X-Debug-Role")


class HasRole(BasePermission):
    """ViewSet 에 required_roles = {"reception"} 처럼 선언해서 쓴다.

    required_roles 가 비어 있으면 통과. resolve_role() 이 None 을 주는
    동안(=인증 미구현)에도 통과시켜 개발을 막지 않는다.
    """

    def has_permission(self, request, view):
        required = getattr(view, "required_roles", None)
        if not required:
            return True
        role = resolve_role(request)
        if role is None:
            return True  # TODO(auth): 인증 붙으면 False 로
        return role in required
