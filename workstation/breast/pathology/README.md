# 이 폴더는 동결되었습니다 (2026-08-30)

병리(유방 sTIL) 작업은 더 이상 여기서 진행하지 않습니다.

## 최신 코드는 여기로

- 로컬: `~/pathology-eval`
- 원격: https://github.com/medical-ai-group-3/empatho-pathology-eval

## 왜?

이 폴더는 2026-08-30 상태로 멈춰 있으며, 아래가 반영되어 있지 않습니다:

- 세포검출 recall 수정 (큰 이미지 타일링)
- sTIL 표준 공식 (국제 TIL Working Group 정의)
- 소켓2 분류기 weighted 재학습
- WSI 파이프라인 / 서빙 패키지 / 평가 스크립트

구 폴더 전체는 2026-09-02 에 삭제되었습니다. 대부분 pathology-eval 에 중복되어 있었고,
유일하게 다른 데 없던 **소켓2 weighted 재학습 이전 체크포인트·로그**만
`~/pathology-eval/candidates/socket2/_pre_weighted_2026-08-26/` 에 보존했습니다.
옛 코드 버전은 pathology-eval git 히스토리에서 복구할 수 있습니다.
