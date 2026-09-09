// Package report — 워크스테이션 리포트 서버 호출.
//
// 2026-09-02 이전에는 Go 가 Ollama 를 직접 불렀다. 지금은 안 부른다.
// 소견 생성 · 숫자 검사 · 근거 검사가 전부 리포트 서버 안에서 끝나고,
// Go 는 판독 결과를 넘기고 결과를 받아 Django 로 옮기는 일만 한다.
//
// 왜 흘려보내지(스트리밍) 않나
//
//	검사가 문장 전체를 봐야 한다. "63.9px 가 그대로 있나" 도, "근거 표시가
//	붙었나" 도 문장이 끝나야 판정할 수 있다. 검사에 걸리면 모델 출력을
//	버리고 뼈대 문장으로 되돌리는데, **이미 흘려보낸 글자는 되돌릴 수 없다.**
//	틀린 숫자를 잠깐 보여줬다가 고치는 것은 판독 화면에서 할 일이 아니다.
//
//	실측으로 소견 하나가 1초 미만이다(모델 적재된 뒤). 기다릴 만하다.
//
// 주소
//
//	REPORT_BASE=http://tunnel:8002
//
//	tunnel 은 compose 안의 터널 컨테이너다. 워크스테이션의 8002 로 SSH
//	포트 넘김을 걸어 두고 restart: unless-stopped 로 스스로 살아난다.
//
//	이전에는 host.docker.internal:18002 였다. 사람이 Windows 에서 손으로
//	ssh -L 을 띄우는 방식이었는데, **아무도 안 띄우면 앱 전체가 멈췄다.**
//	컨테이너로 옮기면서 주소가 서비스 이름이 됐고, 배포하는 사람이
//	잊어버릴 자리가 없어졌다.
//
// ⚠ 그래도 워크스테이션이 꺼져 있으면 안 닿는다. 남의 기계라 우리가 어쩔
//
//	수 없다. 그때 무엇이 문제인지 바로 보이도록 ErrUnreachable 를 따로 둔다.
package report

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net/http"
	"regexp"
	"strings"
	"time"
)

var (
	// ErrUnreachable — 리포트 서버에 닿지 못했다. 십중팔구 터널이 안 떠 있다.
	ErrUnreachable = errors.New("리포트 서버에 닿지 못했다")
	// ErrUpstream — 닿았는데 서버가 오류를 냈다.
	ErrUpstream = errors.New("리포트 서버가 오류를 냈다")
	// ErrBadSocket — 소켓 이름이 주소에 넣기 안전하지 않다.
	ErrBadSocket = errors.New("소켓 이름이 올바르지 않다")
)

// socketRe — 소켓 이름은 그대로 주소 경로에 들어간다(/report/{socket}).
//
// ⚠ 검사 없이 넣으면 "../.." 같은 값으로 리포트 서버의 **다른 경로를
//
//	부를 수 있다.** 이 값은 바깥에서 온 요청 본문에 실려 오므로 반드시
//	막는다. 흰 목록 방식이라 새 소켓이 생기면 여기가 아니라 형식만 맞으면 된다.
var socketRe = regexp.MustCompile(`^[a-z0-9][a-z0-9_-]{0,31}$`)

// Request — 리포트 서버로 보내는 것. 이게 전부다.
//
// Evidence 는 **ID 목록만** 보낸다. 좌표도 화소 간격도 안 보낸다.
// 리포트 서버가 하는 근거 검사는 "모델이 인용한 ID 가 이 목록 안에 있나"
// 뿐이라 좌표를 볼 일이 없고, 프롬프트가 밀리미터 환산을 금지하고 있어
// 간격도 쓸 데가 없다. 행은 우리가 들고 있다가 나중에 합친다.
//
// 비워 보내면 근거 검사를 건너뛰고 숫자 검사만 한다. 병변이 없을 때가
// 그 경우다.
type Request struct {
	Result   json.RawMessage `json:"result"`
	Evidence []string        `json:"evidence"`
}

// Note — 코드가 붙인 고정 안내 문구. 모델이 쓴 글이 아니다.
type Note struct {
	ID   string `json:"id"`
	Text string `json:"text"`
}

// Dropped — 검사에 걸려 버려진 문장.
type Dropped struct {
	Sentence string `json:"sentence"`
	Reason   string `json:"reason"`
}

// Response — 리포트 서버가 돌려주는 것.
//
// ⚠ 키 이름이 한국어와 영어가 섞여 있다. 리포트 서버 쪽 형식이라 우리가
//
//	정한 게 아니다. Go 에서는 태그로 받으면 그만이라 동작에 문제는 없다.
type Response struct {
	Text          string    `json:"소견"`
	Notes         []Note    `json:"안내"`
	Evidence      []string  `json:"evidence"` // 실제로 인용된 것만
	Dropped       []Dropped `json:"dropped"`
	Fallback      *string   `json:"fallback"` // 뼈대 문장으로 되돌렸으면 그 사유
	PromptVersion string    `json:"prompt_version"`
}

type Client struct {
	Base string
	HTTP *http.Client
}

// New — timeout 은 넉넉해야 한다. 소견 하나는 1초 미만이지만 **모델이
// 내려가 있으면 적재에 3초가 더 붙고**, 다른 요청이 앞에 줄 서 있으면
// 그만큼 더 걸린다. 짧게 잡으면 멀쩡한 요청이 끊긴다.
func New(base string, timeout time.Duration) *Client {
	if timeout <= 0 {
		timeout = 2 * time.Minute
	}
	return &Client{
		Base: strings.TrimRight(base, "/"),
		HTTP: &http.Client{Timeout: timeout},
	}
}

// Narrate — POST /report/{socket}
func (c *Client) Narrate(ctx context.Context, socket string, req Request) (*Response, error) {
	if !socketRe.MatchString(socket) {
		return nil, fmt.Errorf("%w: %q", ErrBadSocket, socket)
	}
	// evidence 가 nil 이면 JSON 에 null 로 나간다. 받는 쪽이 목록을
	// 기대하므로 빈 배열로 맞춘다 — "근거 없음" 과 "칸이 없음" 은 다르다.
	if req.Evidence == nil {
		req.Evidence = []string{}
	}
	if len(req.Result) == 0 {
		req.Result = json.RawMessage("null")
	}

	body, err := json.Marshal(req)
	if err != nil {
		return nil, err
	}
	url := c.Base + "/report/" + socket
	hr, err := http.NewRequestWithContext(ctx, http.MethodPost, url,
		bytes.NewReader(body))
	if err != nil {
		return nil, err
	}
	hr.Header.Set("Content-Type", "application/json")

	res, err := c.HTTP.Do(hr)
	if err != nil {
		// 연결 자체가 안 된 경우다. 터널이 안 떠 있으면 여기로 온다.
		return nil, fmt.Errorf("%w (%s): %v", ErrUnreachable, url, err)
	}
	defer res.Body.Close()

	// 오류 본문은 앞부분만 본다. 통째로 읽으면 서버가 HTML 오류 페이지를
	// 돌려줄 때 로그가 통째로 더러워진다.
	if res.StatusCode != http.StatusOK {
		snippet, _ := io.ReadAll(io.LimitReader(res.Body, 512))
		return nil, fmt.Errorf("%w: %d %s", ErrUpstream, res.StatusCode,
			strings.TrimSpace(string(snippet)))
	}

	var out Response
	if err := json.NewDecoder(io.LimitReader(res.Body, 1<<20)).Decode(&out); err != nil {
		return nil, fmt.Errorf("%w: 응답을 못 읽었다: %v", ErrUpstream, err)
	}
	return &out, nil
}

// Health — 터널이 살아 있는지 본다. 안 떠 있는 일이 잦아서 따로 둔다.
func (c *Client) Health(ctx context.Context) error {
	hr, err := http.NewRequestWithContext(ctx, http.MethodGet, c.Base+"/health", nil)
	if err != nil {
		return err
	}
	res, err := c.HTTP.Do(hr)
	if err != nil {
		return fmt.Errorf("%w (%s): %v", ErrUnreachable, c.Base, err)
	}
	defer res.Body.Close()
	io.Copy(io.Discard, io.LimitReader(res.Body, 4096))
	if res.StatusCode != http.StatusOK {
		return fmt.Errorf("%w: %d", ErrUpstream, res.StatusCode)
	}
	return nil
}
