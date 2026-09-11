"""ViewSet 공통 믹스인."""



class AuditMixin:
    """생성·수정 시 감사 컬럼(created_by / updated_by)을 채운다.

    전 테이블 공통 컬럼(AuditBase). created_at·updated_at 은 모델이
    auto_now_add·auto_now 로 처리하므로 여기서는 *_by 만 손댄다.

    TODO(auth): 인증이 붙으면 self.request.user 와 이어진 Account 를 넣는다.
    지금은 None 으로 둔다(컬럼이 null 허용).
    """

    def _current_account(self):
        return self.request.user if self.request.user.is_authenticated else None

    def perform_create(self, serializer):
        serializer.save(created_by=self._current_account(),
                        updated_by=self._current_account())

    def perform_update(self, serializer):
        serializer.save(updated_by=self._current_account())


