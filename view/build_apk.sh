#!/usr/bin/env bash
# APK 한 벌 만들기.
#   · capacitor.config.json 은 빌드용으로만 바꾸고 반드시 되돌린다
#   · Capacitor 8 은 JDK 21 이 필요하다 (JAVA_HOME 의 17 로는 source release 21 오류)
#   · gradle 이 실패하면 낡은 APK 를 복사하지 않는다
set -u
cd "$(dirname "$0")"

# Android Studio 번들 JDK 21
JBR="/c/Program Files/Android/Android Studio/jbr"
if [ -x "$JBR/bin/java.exe" ]; then
  export JAVA_HOME="C:\\Program Files\\Android\\Android Studio\\jbr"
  echo "[JDK] $("$JBR/bin/java.exe" -version 2>&1 | head -1)"
else
  echo "[경고] JDK 21 을 못 찾았다 — 현재 JAVA_HOME 으로 진행"
fi

CFG=capacitor.config.json
BAK=capacitor.config.json.bak
restore() { [ -f "$BAK" ] && mv -f "$BAK" "$CFG" && echo "[복구] $CFG 원래대로"; }
trap restore EXIT

APK=android/app/build/outputs/apk/debug/app-debug.apk
rm -f "$APK"                      # 낡은 산출물을 지워 실패를 성공으로 오인하지 않는다

cp "$CFG" "$BAK"
python - <<'PY'
import json
p = "capacitor.config.json"
c = json.load(open(p, encoding="utf-8"))
# 앱은 fetch("/api/v1/…") 상대경로를 쓴다 — 서버 주소에서 열려야 API 가 붙는다.
c["server"] = {"url": "https://empatho.example.com", "cleartext": False}
json.dump(c, open(p, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
print("[빌드용 설정]", c["server"])
PY

echo "=== 1/3 웹 빌드 ==="
npm run build >/tmp/web.log 2>&1 || { echo "[실패] npm run build"; tail -15 /tmp/web.log; exit 1; }
echo "  dist 생성됨"

echo "=== 2/3 capacitor sync ==="
npx cap sync android >/tmp/sync.log 2>&1 || { echo "[실패] cap sync"; tail -15 /tmp/sync.log; exit 1; }
echo "  sync 완료"

echo "=== 3/3 gradle assembleDebug ==="
( cd android && ./gradlew.bat assembleDebug --console=plain ) >/tmp/gradle.log 2>&1
RC=$?
if [ $RC -ne 0 ]; then
  echo "[실패] gradle 종료코드 $RC"
  grep -E "error:|FAILURE|What went wrong" -A 4 /tmp/gradle.log | head -25
  exit 1
fi
tail -3 /tmp/gradle.log

if [ ! -f "$APK" ]; then echo "[실패] APK 가 안 만들어졌다"; exit 1; fi
OUT="/c/Users/401/Desktop/EMPATHO_patient.apk"
cp "$APK" "$OUT"
echo "[완료] $OUT  $(du -h "$OUT" | cut -f1)  $(date -r "$OUT" '+%m-%d %H:%M')"
