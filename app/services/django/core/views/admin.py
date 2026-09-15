"""관리자(admin) view."""

from rest_framework import viewsets, status, generics
from rest_framework.response import Response

from django.utils import timezone

from .. import models, serializers
from ..mixins import AuditMixin
from core.api.permissions import IsRole, ADMIN
from core.api.errors import ApiError


class StaffApprovalListView(generics.ListAPIView):
    """§7-1 GET /admin/approvals — 승인 대기/완료 목록."""

    resource = "admin"  # 매트릭스에 없으므로 permission_classes 로만 판정
    permission_classes = [IsRole.of(ADMIN)]
    serializer_class = serializers.StaffApprovalSerializer

    def get_queryset(self):
        qs = models.Staff.objects.select_related("account").all()
        status_param = self.request.query_params.get("status")
        if status_param == "pending":
            qs = qs.filter(approved_at__isnull=True)
        elif status_param == "approved":
            qs = qs.filter(approved_at__isnull=False)
        return qs


class StaffApproveView(AuditMixin, viewsets.ViewSet):
    """§7-1 PATCH /admin/approvals/{id} — 가입 승인."""

    permission_classes = [IsRole.of(ADMIN)]

    def partial_update(self, request, pk=None):
        staff = models.Staff.objects.get(pk=pk)
        serializer = serializers.StaffApproveSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        admin_account = self._current_account()
        admin_staff = getattr(admin_account, "staff", None) if admin_account else None

        staff.approved_by = admin_staff
        staff.approved_at = timezone.now()
        staff.updated_by = admin_account
        staff.save()

        if "role" in data:
            staff.account.role = data["role"]
            staff.account.updated_by = admin_account
            staff.account.save()

        out = serializers.StaffApprovalSerializer(staff)
        return Response(out.data)


class AccountRoleView(AuditMixin, viewsets.ViewSet):
    """§7-1 PATCH /admin/accounts/{id}/role — 부서 재지정."""

    permission_classes = [IsRole.of(ADMIN)]

    def partial_update(self, request, pk=None):
        account = models.Account.objects.get(pk=pk)
        serializer = serializers.AccountRoleSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        account.role = serializer.validated_data["role"]
        account.updated_by = self._current_account()
        account.save()

        return Response({"account_id": account.account_id, "role": account.role})