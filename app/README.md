# empatho-app

앱 서버. 공유 데이터(PostgreSQL · Garage · Orthanc)와 앱 서비스가 들어간다.

## 지금 있는 것

`compose.server.yml` — 공유 데이터 세 종. 서버에서만 띄운다.

```bash
docker compose -f compose.server.yml up -d
```

Django · worker · gateway 는 아직 없다.

---

## 접속 정보

포트가 전부 `127.0.0.1` 에 묶여 있다. **사내망에서 직접 못 붙는다.**
서버 것에 붙어야 하면 SSH 터널을 쓴다.

### PostgreSQL

```
버전       17 (서버가 17.11 — 로컬도 17 로 맞출 것)
DB         empatho
사용자      empatho
비밀번호    따로 전달
포트        5432
```

개발은 각자 PC 에 설치한 postgres 로 한다. 서버 것에 붙을 때만 터널을 연다.

```bash
ssh -L 15432:127.0.0.1:5432 사용자@서버주소
# 그 뒤 127.0.0.1:15432 로 접속
```

로컬 5432 와 겹치지 않게 다른 포트로 연다.

### Garage (S3 호환 파일 저장)

```
엔드포인트   http://127.0.0.1:3900
region      garage
액세스 키    따로 전달
버킷        empatho-original · empatho-derived
```

**`root_domain` 이 설정돼 있지 않다.** S3 클라이언트에서 **path-style** 로 붙어야 한다.
virtual-host style(`버킷명.호스트`) 은 실패한다.

```python
boto3.client(
    "s3",
    endpoint_url="http://127.0.0.1:3900",
    region_name="garage",
    config=Config(s3={"addressing_style": "path"}),
)
```

### Orthanc (DICOM)

```
URL      http://127.0.0.1:8042
계정      따로 전달
```

DICOMweb 이 켜져 있다.

### 워크스테이션 추론 서버

앱 서버에서 직접 못 붙는다. SSH 터널로 연결한다.

```bash
ssh -L 18001:127.0.0.1:8001 -L 18002:127.0.0.1:8002 -p 22 wsuser@ws-host
```

```
18001   판독      POST /analyze/{socket_id}   multipart 로 영상 1장
18002   리포트    POST /report/{socket_id}    판독 결과 JSON
```

판독은 **기권해도 HTTP 200** 이다. `abstained` 를 확인할 것.
오류로 처리하면 경로가 끊긴다.

---

## 비밀값

`conf/postgres.env` · `conf/orthanc.env` · `conf/garage.toml` 은 git 에 없다.
`.example` 을 복사해서 채운다. 값은 서버 담당에게 받는다.

```bash
cp conf/postgres.env.example conf/postgres.env
```

**따옴표를 쓰지 않는다.** `env_file` 은 따옴표를 값의 일부로 읽을 수 있고,
postgres 는 볼륨을 처음 만들 때의 비밀번호로 고정되므로 나중에 고치기 번거롭다.
