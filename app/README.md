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

---

## 데이터가 어디에 있나

세 서비스의 데이터는 전부 **Docker 이름 볼륨**에 들어간다. 레포 폴더에는 쌓이지 않는다.
배포가 폴더를 통째로 갈아도 데이터는 남는다.

```bash
docker volume ls --filter name=empatho-server
```

`down` 은 볼륨을 건드리지 않는다. **`down -v` 는 지운다.**

### garage 가 마커 파일을 못 찾을 때

`garage-data` 볼륨만 새로 만들면 garage 가 뜨지 않고 이 말을 남긴다.

```
Could not find expected marker file `garage-marker` in data directory
```

엉뚱한 디렉토리에 붙은 게 아닌지 확인하는 안전장치다. 값을 다시 넣어 준다.

```bash
docker run --rm --entrypoint sh -v empatho-server_garage-data:/d postgres:17 \
  -c "printf '%s' 'ef5b0238fd779162bcd18a0e6be2b65dde1e22d71c8fe139c1c66dc4009f8388' > /d/garage-marker"
```

`garage-meta` 까지 새것이면 이 값은 필요 없다 — garage 가 직접 만든다.
메타는 남고 데이터만 새것일 때만 쓰인다.
