// Package httpx — 세 서비스가 함께 쓰는 HTTP 껍데기.
//
// CORS 가 여기 있는 이유
//
//	Go 를 따로 둔 목적이 **브라우저가 Django 를 안 거치고 바이트를 직접
//	주고받는 것**이다(명세 19장). 그러면 브라우저에게 프런트(:3000)와
//	Go(:8091)는 서로 다른 출처다.
//
//	교차 출처 요청에 Authorization 헤더가 붙으면 브라우저는 본 요청 전에
//	OPTIONS 사전 요청을 먼저 보낸다. 여기에 답하지 않으면 **업로드가
//	시작조차 안 된다.** 화면에는 애매한 network error 만 뜬다.
//
// ⚠ 리버스 프록시(nginx 하나로 프런트와 Go 를 같은 출처로 묶는 구성)를
//
//	쓰면 CORS 자체가 필요 없다. 그때는 CORS_ORIGINS 를 비워 두면 된다.
//	비어 있으면 이 미들웨어는 아무것도 안 한다.
package httpx

import (
	"log"
	"net/http"
	"strings"
)

// 허용 헤더. 우리가 실제로 쓰는 것만 넣는다.
//
//	Authorization  티켓
//	X-Ticket       티켓 (Authorization 을 못 쓰는 경우)
//	X-Filename     G-F4 의 원본 파일명 (확장자만 쓴다)
//	Content-Type   업로드 본문 종류
//	Range          부분 내려받기 — 뷰어가 쓴다
const allowHeaders = "Authorization, X-Ticket, X-Filename, Content-Type, Range"

// 브라우저가 **읽을 수 있게** 열어 줄 응답 헤더.
//
// 이걸 안 열면 자바스크립트에서 Content-Range 를 못 읽는다. 교차 출처에서는
// 기본적으로 몇 개(Content-Type 등) 말고는 전부 가려진다. 타일 뷰어가
// 부분 요청 결과를 조립하려면 Content-Range 가 보여야 한다.
const exposeHeaders = "Content-Range, Content-Length, Accept-Ranges, ETag"

type cors struct {
	next    http.Handler
	allowed map[string]bool
	any     bool // CORS_ORIGINS=* — 개발용
}

// CORS — origins 가 비면 감싸지 않고 그대로 돌려준다.
//
// origins 는 쉼표로 나눈 목록이다. 예:
//
//	CORS_ORIGINS=http://localhost:3000,https://cdss.example.org
//
// "*" 도 받지만 **개발용이다.** 티켓을 헤더로 보내므로 아무 사이트나
// 우리 API 를 부를 수 있게 된다. 운영에서는 출처를 적어야 한다.
func CORS(next http.Handler, origins string) http.Handler {
	origins = strings.TrimSpace(origins)
	if origins == "" {
		log.Printf("[cors] CORS_ORIGINS 가 비어 있다 — 교차 출처 요청을 안 받는다. " +
			"브라우저가 이 서비스를 직접 부른다면 설정하거나 리버스 프록시로 같은 출처로 묶을 것")
		return next
	}
	c := &cors{next: next, allowed: map[string]bool{}}
	for _, o := range strings.Split(origins, ",") {
		o = strings.TrimSpace(strings.TrimSuffix(o, "/"))
		if o == "*" {
			c.any = true
			log.Printf("[cors] ⚠ 모든 출처를 허용한다(*). 개발용이다 — " +
				"운영에서는 출처를 명시할 것")
			continue
		}
		if o != "" {
			c.allowed[o] = true
		}
	}
	if !c.any {
		log.Printf("[cors] 허용 출처 %d개", len(c.allowed))
	}
	return c
}

func (c *cors) ServeHTTP(w http.ResponseWriter, r *http.Request) {
	origin := strings.TrimSuffix(r.Header.Get("Origin"), "/")

	if origin != "" && (c.any || c.allowed[origin]) {
		// ⚠ 실제 출처를 그대로 되돌려준다. "*" 를 쓰면 안 된다 —
		//   Authorization 을 붙인 요청에는 브라우저가 "*" 를 거부한다.
		w.Header().Set("Access-Control-Allow-Origin", origin)
		// 출처마다 응답이 달라지므로 캐시가 섞이지 않게 알린다.
		w.Header().Add("Vary", "Origin")
		w.Header().Set("Access-Control-Expose-Headers", exposeHeaders)
	}

	// 사전 요청 — 본 요청 전에 브라우저가 먼저 물어보는 것
	if r.Method == http.MethodOptions && r.Header.Get(
		"Access-Control-Request-Method") != "" {
		w.Header().Add("Vary", "Access-Control-Request-Method")
		w.Header().Add("Vary", "Access-Control-Request-Headers")
		if origin == "" || !(c.any || c.allowed[origin]) {
			// 허용 목록 밖이다. 헤더를 안 붙이고 끝낸다 —
			// 브라우저가 알아서 본 요청을 막는다.
			w.WriteHeader(http.StatusForbidden)
			return
		}
		w.Header().Set("Access-Control-Allow-Methods",
			"GET, POST, PUT, OPTIONS")
		w.Header().Set("Access-Control-Allow-Headers", allowHeaders)
		// 10분간 사전 요청을 다시 안 보내게 한다. 청크 업로드는 조각마다
		// PUT 을 보내는데 그때마다 사전 요청이 붙으면 왕복이 두 배가 된다.
		w.Header().Set("Access-Control-Max-Age", "600")
		w.WriteHeader(http.StatusNoContent)
		return
	}

	c.next.ServeHTTP(w, r)
}
