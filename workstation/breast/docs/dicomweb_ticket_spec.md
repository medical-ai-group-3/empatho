# 19-1 확장안 — DICOMweb 조회 티켓 (purpose: dicom_view)

기존 전송 티켓(업로드·다운로드용)과 동일한 서명 방식을 재사용한다. 신규 인프라 없음.

## 클레임 추가

| 클레임 | 값 |
|---|---|
| purpose | `dicom_view` (신규) |
| study_uid | 조회 대상 study의 DICOM UID |
| patient_id | 권한 확인용 |
| exp | 5분 |
| nonce | 1회용 (재사용 시 401 TICKET_EXPIRED와 동일 처리) |

## 엔드포인트

| # | Method · Endpoint | 설명 |
|---|---|---|
| G-D1 (신규) | POST `/svc/v1/dicom-view/ticket` | Django가 study_uid 기준 권한 확인 후 티켓 발급 |
| G-D2 (신규) | GET `/svc/v1/dicom-view/{ticket}/dicom-web/studies/{study_uid}/...` | Go가 티켓 검증 → Orthanc DICOMweb으로 프록시 |

## 처리 흐름

1. Cornerstone3D가 study_uid를 들고 Django `/svc/v1/dicom-view/ticket` 호출
2. Django: 해당 study가 요청자에게 권한 있는지 확인 (기존 검체·환자 바인딩 규칙 재사용) → 티켓 서명 발급
3. Cornerstone3D는 WADO-RS 요청을 Go 프록시(`G-D2`)로 보냄, 헤더에 티켓 포함
4. Go: 티켓 서명·만료·study_uid 일치 검증 → 통과 시 서버 내부에 저장된 Orthanc Basic Auth로 Orthanc DICOMweb에 요청 후 응답 그대로 릴레이
5. 실패 시 401 TICKET_EXPIRED / 403 TICKET_SCOPE_MISMATCH (기존 코드 재사용)

## 원칙 위반 여부 체크

- Go는 자체 권한 판정 없음 — 원칙 그대로 유지
- Orthanc 계정 정보는 Go 서버 환경변수에만 존재, 프론트/DB 어디에도 저장 안 함
- Django가 여전히 단일 진실 원천 — 원안(프론트→Orthanc 직결)의 Q9 문제 해소

## 남은 결정 사항

- [ ] Go 프록시가 Orthanc 응답을 그대로 스트리밍할지, 캐싱할지 (볼륨 반복 조회 시 성능)
- [ ] Q9 자체를 "해결됨"으로 API 명세서 18장에서 갱신 — 오늘 문서 정리 시 반영
