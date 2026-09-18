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

    def test_common_perms_not_duplicated(self):
        for role in ROLE_PERMS:
            perms = perms_for_role(role)
            self.assertEqual(len(perms), len(set(perms)))
