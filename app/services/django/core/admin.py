"""core 앱 모델 전부 admin 에 등록한다."""

from django.apps import apps
from django.contrib import admin

for model in apps.get_app_config('core').get_models():
    admin.site.register(model)
