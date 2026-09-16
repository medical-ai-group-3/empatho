# Django 가 뜰 때 Celery 앱을 함께 올린다.
# 이게 없으면 @shared_task 가 어느 앱에 붙을지 몰라 워커가 태스크를 못 찾는다.
from .celery import app as celery_app

__all__ = ("celery_app",)

