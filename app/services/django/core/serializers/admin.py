"""관리자(admin) serializer."""

from rest_framework import serializers

from .. import models

AUDIT_FIELDS = ("created_at", "created_by", "updated_at", "updated_by")


class StaffApprovalSerializer(serializers.ModelSerializer):
    """승인 대기 목록용."""

    account_role = serializers.CharField(source="account.role", read_only=True)

    class Meta:
        model = models.Staff
        exclude = AUDIT_FIELDS


class StaffApproveSerializer(serializers.Serializer):
    """PATCH /admin/approvals/{id} — 가입 승인. role 변경 옵션 포함."""

    role = serializers.ChoiceField(
        choices=models.as_choices(["reception", "nursing", "radiology", "surgery", "pathology"]),
        required=False,
    )


class AccountRoleSerializer(serializers.Serializer):
    """PATCH /admin/accounts/{id}/role — 부서 재지정."""

    role = serializers.ChoiceField(
        choices=models.as_choices(["reception", "nursing", "radiology", "surgery", "pathology"])
    )