"""Celery 앱. worker 컨테이너가 -A cdss_backend 로 이것을 찾는다.

Django 가 ai_result(queued) 를 만들고 여기에 일감을 넣으면, 워커가 꺼내
워크스테이션 FastAPI 를 부른다. 결과는 워커가 DB 에 기록한다.
"""
import os 

from celery import Celery 

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "cdss_backend.settings")

app = Celery("cdss_backend")

# CELERY_ 설정을 Django 가 그대로 가져온다 
# 설정이 두 곳에 흩어지지 않게 settings.py 한 곳만 확인 
app.config_from_object("django.conf:settings", namespace="CELERY")

# 각 앱의 tasks.py를 알아서 찾는다. 앱을 더해도 여기는 안 고침 
app.autodiscover_tasks() 