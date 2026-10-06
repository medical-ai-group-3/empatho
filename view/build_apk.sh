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

API_ORIGIN="${API_ORIGIN:-https://empatho.example.com}"

cp "$CFG" "$BAK"
python - <<'PY'
import json
p = "capacitor.config.json"
c = json.load(open(p, encoding="utf-8"))
# 앱은 화면 파일을 자기가 들고 돈다 — server.url 을 없앤다.
#   웹의 / 는 의료진 화면이라(커밋 ceebfbf) 서버 주소를 열면 안 된다.
# 서버는 api.js 가 VITE_API_ORIGIN 으로 박아 둔 주소로 부른다.
c.pop("server", None)
# 본인인증 복귀 중계 페이지(signup-return.html)를 앱 안에서 연다
c["server"] = {"allowNavigation": ["empatho.example.com"]}
# CapacitorHttp — fetch 를 네이티브 요청으로 보낸다. 앱의 출처는
# https://localhost 라 브라우저로 부르면 CORS 에 걸리는데, 네이티브로 가면
# 그 검사 자체가 없다. 서버의 허용 출처 목록을 안 건드려도 된다.
c.setdefault("plugins", {})["CapacitorHttp"] = {"enabled": True}
json.dump(c, open(p, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
print("[빌드용 설정] 번들 모드 · CapacitorHttp 켜짐")
PY

echo "=== 1/3 웹 빌드 (API_ORIGIN=$API_ORIGIN) ==="
VITE_API_ORIGIN="$API_ORIGIN" npm run build >/tmp/web.log 2>&1 \
  || { echo "[실패] npm run build"; tail -15 /tmp/web.log; exit 1; }
grep -q "$API_ORIGIN" dist/assets/*.js 2>/dev/null \
  && echo "  dist 에 서버 주소 박힘 확인" \
  || { echo "[실패] dist 에 API 주소가 안 들어갔다"; exit 1; }

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
