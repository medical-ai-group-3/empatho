# -*- coding: utf-8 -*-
"""09-18 팀 확인: 관리자는 COMMON_PERMS(report.view.all) 를 못 받는다."""
from django.test import SimpleTestCase

from core.api.perms import COMMON_PERMS, ROLE_PERMS, perms_for_role


class PermsForRoleTests(SimpleTestCase):
    def test_admin_does_not_get_common_perms(self):
        perms = perms_for_role("admin")
        for common in COMMON_PERMS:
            self.assertNotIn(common, perms)
        self.assertEqual(perms, ROLE_PERMS["admin"])

    def test_other_roles_still_get_common_perms(self):
        for role in ("reception", "nursing", "radiology", "pathology", "surgery"):
            perms = perms_for_role(role)
            for common in COMMON_PERMS:
                self.assertIn(common, perms)

    def test_role_permissions_are_returned_without_extra_function_merge(self):
        expected = {
            "reception": ROLE_PERMS["reception"],
            "nursing": ROLE_PERMS["nursing"],
            "radiology": ROLE_PERMS["radiology"],
            "pathology": ROLE_PERMS["pathology"],
            "surgery": ROLE_PERMS["surgery"],
            "admin": ROLE_PERMS["admin"],
        }
        for role, role_perms in expected.items():
            self.assertEqual(perms_for_role(role), role_perms)

    def test_common_perms_not_duplicated(self):
        for role in ROLE_PERMS:
            perms = perms_for_role(role)
            self.assertEqual(len(perms), len(set(perms)))
