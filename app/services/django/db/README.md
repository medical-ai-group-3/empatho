# DB 백업

```
cdss_schema.sql   스키마 전용 덤프 (데이터 없음). django_* · auth_* 포함
migrations/       스키마를 바꾼 SQL. 파일명은 날짜-제목
```

## 스키마 변경 규칙

**스키마를 바꾸면 SQL 파일로 남긴다.** `migrations/<날짜>-<제목>.sql` 로 두고
머리말에 무엇을 왜 바꿨는지 적는다. 그 다음 `cdss_schema.sql` 을 다시 뜬다.

### Django 마이그레이션은 스키마 이력이 아니다

`core` 의 모델은 전부 `managed = False` 다. 여기서 두 가지가 따라온다.

**① `migrate` 는 DDL 을 내지 않는다.** 표를 만들고 고치는 것은 사람이 SQL 로 한다.
마이그레이션 파일은 Django 의 상태 기록일 뿐이다.

**② `makemigrations` 가 필드 변경을 아예 보지 않는다.** autodetector 는 unmanaged
모델에 대해 **모델 생성·삭제만** 감지한다. 컬럼을 추가하거나 FK 를 바꿔도
마이그레이션이 생기지 않는다.

그래서 이렇게 된다.

```bash
python manage.py makemigrations core --check --dry-run
# No changes detected  ← 필드가 맞다는 뜻이 아니다. 애초에 안 본다.
```

**이 명령이 통과해도 모델과 DB 가 일치한다는 보장이 없다.** 실제로 맞는지 보려면
`information_schema` 를 직접 조회해서 대조해야 한다.

스키마의 원본은 `cdss_schema.sql` 과 `migrations/` 다. 마이그레이션 파일의 diff 로
"언제 무엇이 바뀌었나"를 추적하려 하면 안 된다.

## 다시 만들 때

```bash
cd services/django
PGPASSWORD=<비번> pg_dump -h 127.0.0.1 -p 15432 -U empatho -d empatho \
    --schema-only --no-owner --no-privileges -f db/cdss_schema.sql
```

포트 15432 는 SSH 터널이다 (`ssh -N -L 15432:127.0.0.1:5432 <계정>@<서버>`).
서버에서 직접 뜬다면 `-p 5432` 다.

pg_dump 17.11 은 파일 앞뒤에 `\restrict` · `\unrestrict` 를 붙인다.
psql 전용 메타명령이라 HeidiSQL 같은 클라이언트에서 `invalid command` 로 막힌다.
**뜬 뒤에 그 두 줄을 지운다.** 지금 올라가 있는 덤프는 지운 상태다.

## 복원 (새 서버)

DB `empatho` 와 사용자 `empatho` 는 postgres 컨테이너가 `conf/postgres.env` 를 보고
처음 뜰 때 만든다. `createuser` · `createdb` 를 따로 하지 않는다.

```bash
PGPASSWORD=<비번> psql -h 127.0.0.1 -p 15432 -U empatho -d empatho -f db/cdss_schema.sql

cd services/django
cp ../../conf/web.env.example .env   # 값을 채운다. 터널이면 DB_HOST=127.0.0.1 · DB_PORT=15432
python manage.py migrate --fake
python manage.py makemigrations core --check --dry-run   # "No changes" 여야 정상
```

venv 를 켜고 돌린다 — Windows 는 `.\venv\Scripts\activate`, 리눅스는 `. venv/bin/activate`.

`--no-owner --no-privileges` 라 다른 사용자 이름으로도 복원된다.

`--fake-initial` 이 아니라 `--fake` 다. `--fake-initial` 은 initial 만 가짜 처리하고
나머지는 실제로 실행하는데, 이 덤프에는 `django_content_type.name` 이 이미 없어서
`contenttypes.0002` 가 `column "name" does not exist` 로 죽는다.
스키마가 이미 최종 상태이므로 전부 기록만 하면 된다.

**데이터는 들어 있지 않다.** 데이터까지 백업하려면 `--schema-only` 를 빼고
`-Fc` (커스텀 포맷)로 뜨는 편이 낫다.
