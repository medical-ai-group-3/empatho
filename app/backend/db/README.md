# DB 백업

```
cdss_schema.sql   스키마 전용 덤프 (데이터 없음). django_* · auth_* 포함
```

## 다시 만들 때

```bash
cd ~/workspace/backend
PGPASSWORD=<비번> pg_dump -h localhost -U cdss -d cdss \
    --schema-only --no-owner --no-privileges -f db/cdss_schema.sql
```

## 복원 (새 서버)

```bash
sudo -u postgres createuser cdss --pwprompt
sudo -u postgres createdb cdss -O cdss
PGPASSWORD=<비번> psql -h localhost -U cdss -d cdss -f db/cdss_schema.sql

cd ~/workspace/backend
cp .env.example .env      # 값을 채운다
./venv/bin/python manage.py migrate --fake-initial
./venv/bin/python manage.py makemigrations core --check --dry-run   # "No changes" 여야 정상
```

`--no-owner --no-privileges` 라 다른 사용자 이름으로도 복원된다.
`django_*` · `auth_*` 를 함께 넣었으므로 `--fake-initial` 만으로 끝난다.

**데이터는 들어 있지 않다.** 데이터까지 백업하려면 `--schema-only` 를 빼고
`-Fc` (커스텀 포맷)로 뜨는 편이 낫다.
