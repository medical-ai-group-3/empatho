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

## 두 번 물린 함정 — 테이블을 추가하기 전에 읽을 것

두 건 모두 2026-09-02 에 ORM CRUD 를 실제 DB 로 확인하다 드러났다. 문법 오류가
아니라 **조용히 틀린 값이 저장되는** 종류라, 모르면 한참 뒤에야 발견된다.

### ① 시각 컬럼은 반드시 `timestamptz`

`timestamp without time zone` + `USE_TZ = True` 는 **저장할 때마다 9시간씩 밀린다.**

```
생성 직후  created_at = 2026-09-02 03:14:23
save() 후  created_at = 2026-09-01 18:14:23      ← −9시간
```

DB 가 `DEFAULT now()` 로 UTC 를 timezone 없이 넣는다 → Django 가 naive 로 읽는다
→ `USE_TZ=True` 라 `TIME_ZONE`(Asia/Seoul)으로 간주한다 → 다시 쓸 때 UTC 로 변환한다.
`save()` 를 세 번 부르면 27시간 밀린다.

업무 테이블 35개의 시각 컬럼 106개를 전부 `timestamptz` 로 바꿨다
(`migrations/2026-09-02-timestamptz.sql`). Django 가 직접 만드는 `django_*` ·
`auth_*` 테이블은 처음부터 `timestamptz` 였다 — 업무 테이블만 어긋나 있었다.

**새 테이블을 `timestamp` 로 만들면 같은 문제가 그대로 재발한다.**

### ② 감사 컬럼은 `db_default` · `auto_now` 로 둘 것

`managed = False` 여도 **DB 의 `DEFAULT` 가 자동으로 먹지 않는다.** 필드를 그냥
`null=True` 로 두면 Django 가 INSERT 컬럼 목록에 넣고 `NULL` 을 명시로 보낸다.

```sql
-- 필드가 그냥 null=True 일 때
INSERT INTO patient (..., "created_at", ...) VALUES (..., NULL, ...)
                                                          ↑ DEFAULT now() 가 무시된다
```

그래서 모델을 이렇게 둔다.

```python
created_at = models.DateTimeField(db_default=Now(), blank=True, null=True)
updated_at = models.DateTimeField(auto_now=True, blank=True, null=True)
```

`created_at` 은 `db_default` 라 값이 없으면 컬럼이 INSERT 에서 빠져 DB 기본값이
적용된다. `updated_at` 은 `auto_now` 여야 한다 — DB `DEFAULT` 는 INSERT 때만
동작하고 UPDATE 를 갱신하지 않으며, 갱신 트리거도 없다.

`created_by` · `updated_by` 는 요청자의 `staff_id` 라 DB 가 알 수 없다. API 계층의
믹스인이 채운다 — `models.py` 에 `TODO` 로 표시해 뒀다.

> 참고: `created_at` 은 DB 시계, `updated_at` 은 애플리케이션 시계에서 나온다.
> 같은 호스트에 있으면 차이가 밀리초지만, 원격에서 터널로 붙으면 왕복 지연만큼
> 벌어진다. 두 값의 대소를 비교하는 로직은 두지 말 것.

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
