// Package ollama — Ollama 스트리밍 호출.
//
// 명세 19-4. Go 가 호출하는 LLM 은 Ollama 뿐이다. 소켓 1~5(GPU 추론)는
// Celery → FastAPI 직결이고 Go 를 안 거친다.
//
// Ollama /api/chat 은 줄 단위 JSON 을 흘려보낸다. 한 줄이 한 조각이다.
//
//	{"message":{"role":"assistant","content":"소"},"done":false}
//	{"message":{"role":"assistant","content":"견"},"done":false}
//	{"done":true,"total_duration":123456789, ...}
//
// 그래서 응답 전체를 기다렸다 파싱하면 안 된다 — json.Decoder 로 한 줄씩
// 읽어서 즉시 흘려보낸다.
package ollama

import (
	"bufio"
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"strings"
	"time"
)

type Message struct {
	Role    string `json:"role"`
	Content string `json:"content"`
}

type chatReq struct {
	Model    string         `json:"model"`
	Messages []Message      `json:"messages"`
	Stream   bool           `json:"stream"`
	Options  map[string]any `json:"options,omitempty"`
	Format   string         `json:"format,omitempty"`
}

type chatChunk struct {
	Message struct {
		Content string `json:"content"`
	} `json:"message"`
	Done       bool   `json:"done"`
	DoneReason string `json:"done_reason"`
	Error      string `json:"error"`
}

type Client struct {
	Base  string // http://127.0.0.1:11434
	Model string // medgemma 등
	HTTP  *http.Client
}

func New(base, model string, timeout time.Duration) *Client {
	return &Client{
		Base:  strings.TrimRight(base, "/"),
		Model: model,
		// 스트리밍이라 응답 전체 타임아웃을 짧게 걸면 긴 서술이 잘린다.
		// 대신 호출부에서 context 로 상한을 준다.
		HTTP: &http.Client{Timeout: timeout},
	}
}

// Chat 은 조각이 올 때마다 onChunk 를 부르고, 끝나면 전체 텍스트를 돌려준다.
//
// onChunk 가 error 를 돌려주면 흘려보내기만 멈추고 **읽기는 계속한다**.
// 클라이언트가 중간에 끊어도 생성을 끝까지 받아야 I-4 로 저장할 수 있기
// 때문이다 — 안 그러면 그때까지의 GPU 시간이 통째로 버려진다.
func (c *Client) Chat(ctx context.Context, msgs []Message,
	onChunk func(string) error) (string, error) {

	body, err := json.Marshal(chatReq{Model: c.Model, Messages: msgs, Stream: true})
	if err != nil {
		return "", err
	}
	req, err := http.NewRequestWithContext(ctx, http.MethodPost,
		c.Base+"/api/chat", bytes.NewReader(body))
	if err != nil {
		return "", err
	}
	req.Header.Set("Content-Type", "application/json")

	res, err := c.HTTP.Do(req)
	if err != nil {
		return "", fmt.Errorf("ollama 연결 실패: %w", err)
	}
	defer res.Body.Close()
	if res.StatusCode != http.StatusOK {
		b, _ := io.ReadAll(io.LimitReader(res.Body, 2048))
		return "", fmt.Errorf("ollama %d: %s", res.StatusCode, strings.TrimSpace(string(b)))
	}

	var full strings.Builder
	sc := bufio.NewScanner(res.Body)
	// 한 줄이 길 수 있다. 기본 64KB 로는 모자랄 때가 있어 늘린다.
	sc.Buffer(make([]byte, 0, 64*1024), 4*1024*1024)
	sendOK := true
	for sc.Scan() {
		line := bytes.TrimSpace(sc.Bytes())
		if len(line) == 0 {
			continue
		}
		var ch chatChunk
		if err := json.Unmarshal(line, &ch); err != nil {
			continue // 파싱 못 하는 줄은 건너뛴다. 스트림을 죽이지 않는다
		}
		if ch.Error != "" {
			return full.String(), fmt.Errorf("ollama: %s", ch.Error)
		}
		if ch.Message.Content != "" {
			full.WriteString(ch.Message.Content)
			if sendOK && onChunk != nil {
				if err := onChunk(ch.Message.Content); err != nil {
					sendOK = false // 흘려보내기만 포기. 읽기는 계속한다
				}
			}
		}
		if ch.Done {
			break
		}
	}
	if err := sc.Err(); err != nil {
		return full.String(), fmt.Errorf("ollama 스트림 끊김: %w", err)
	}
	return full.String(), nil
}

type ModelInfo struct {
	Name string `json:"name"`
	Size int64  `json:"size"`
}

// Models — G-L3. Ollama 에 올라와 있는 모델 목록.
func (c *Client) Models(ctx context.Context) ([]ModelInfo, error) {
	req, err := http.NewRequestWithContext(ctx, http.MethodGet, c.Base+"/api/tags", nil)
	if err != nil {
		return nil, err
	}
	res, err := c.HTTP.Do(req)
	if err != nil {
		return nil, err
	}
	defer res.Body.Close()
	var out struct {
		Models []ModelInfo `json:"models"`
	}
	if err := json.NewDecoder(res.Body).Decode(&out); err != nil {
		return nil, err
	}
	return out.Models, nil
}
