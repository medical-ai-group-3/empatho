# -*- coding: utf-8 -*-
"""admin 화면이 쓰는 태그 둘.

둘 다 «파이썬에서만 할 수 있는 것»을 템플릿에 넘겨 주는 일만 한다. 모양은
템플릿이 정한다 — 여기서 마크업을 만들면 색을 바꿀 때 파이썬을 고치게 된다.
"""

from django import template
from django.contrib.admin.templatetags.admin_list import results

register = template.Library()


@register.simple_tag
def filter_chips(cl):
    """필터를 [{title, choices}] 로 편다 (계정 승인 화면의 칩 석 줄).

    ⚠ 템플릿에서 spec.choices 를 그냥 못 쓴다. 그건 changelist 를 받는
      **메서드**라, 인자 없이 부르면 Django 템플릿이 조용히 빈 값을 낸다 —
      오류도 안 나고 칩만 사라진다. 실제로 그렇게 한 번 비어 있었다.
    """
    return [{"title": spec.title, "choices": list(spec.choices(cl))}
            for spec in cl.filter_specs]


@register.simple_tag
def rows_with_objects(cl):
    """[{obj, cells}] — 줄마다 «행 객체»와 «list_display 가 만든 칸들».

    칸을 손으로 다시 그리지 않는 이유 — 그러면 list_display 의 서식(부서
    한글 이름 · 날짜 모양)과 Django 의 고르개(action-select)를 두 벌로
    들게 된다. 줄마다 붙는 단추에는 행 객체가 필요해서 둘을 짝지어 넘긴다.
    """
    return [{"obj": obj, "cells": cells}
            for obj, cells in zip(cl.result_list, results(cl))]
