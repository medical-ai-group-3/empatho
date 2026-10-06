// Package orthanc — Orthanc DICOM 서버에 인스턴스를 올린다. 명세 19-2 G-F7.
//
// ⚠ 이 코드는 **떠 있는 Orthanc 로 검증하지 않았다.** 인스턴스가 없었다.
//
//	REST API 규격(POST /instances, 200/409 의미)에 맞춰 짰고 가짜 서버로
//	시험했다. 실물에 붙일 때 제일 먼저 확인할 것은 인증 방식(기본 인증인지
//	토큰인지)과 409 를 중복으로 볼지 여부다.
//
// 왜 저장소에서 다시 읽어 보내나 — 업로드는 스트림으로 흘려보내므로
// 본문이 메모리에 안 남는다. 수 GB 를 붙들고 있느니 커밋된 객체를 다시
// 읽는 편이 낫다. DICOM 낱장은 수십 MB 라 부담이 없다.
package orthanc

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net/http"
	"strings"
	"time"
)

// ErrDuplicate — 이미 있는 인스턴스다. 재시도로 같은 파일을 두 번 올리면
// 나므로 **실패로 취급하면 안 된다.**
var ErrDuplicate = errors.New("ORTHANC_DUPLICATE")

type Client struct {
	Base string
	User string
	Pass string
	HTTP *http.Client
}

// Result 는 Orthanc 가 돌려주는 식별자들이다. I-2 에 실어 Django 가
// 나중에 Orthanc 를 직접 조회할 수 있게 한다.
type Result struct {
	ID            string `json:"ID"`
	ParentSeries  string `json:"ParentSeries"`
	ParentStudy   string `json:"ParentStudy"`
	ParentPatient string `json:"ParentPatient"`
	Status        string `json:"Status"` // Success · AlreadyStored
}

func New(base, user, pass string) *Client {
	if base == "" {
		return nil // 설정 안 됨 — 호출부가 nil 을 보고 건너뛴다
	}
	return &Client{Base: strings.TrimRight(base, "/"), User: user, Pass: pass,
		HTTP: &http.Client{Timeout: 5 * time.Minute}}
}

// Store — POST /instances. 본문은 DICOM 원본 바이트 그대로다.
func (c *Client) Store(ctx context.Context, r io.Reader) (*Result, error) {
	req, err := http.NewRequestWithContext(ctx, http.MethodPost,
		c.Base+"/instances", r)
	if err != nil {
		return nil, err
	}
	req.Header.Set("Content-Type", "application/dicom")
	if c.User != "" {
		req.SetBasicAuth(c.User, c.Pass)
	}
	res, err := c.HTTP.Do(req)
	if err != nil {
		return nil, err
	}
	defer res.Body.Close()
	body, _ := io.ReadAll(io.LimitReader(res.Body, 1<<16))

	// 409 는 "이미 있다" 다. 재시도가 이걸 만드는 것은 정상이다.
	if res.StatusCode == http.StatusConflict {
		return nil, ErrDuplicate
	}
	if res.StatusCode < 200 || res.StatusCode >= 300 {
		return nil, fmt.Errorf("orthanc %d: %s", res.StatusCode,
			strings.TrimSpace(string(body)))
	}
	var out Result
	if err := json.Unmarshal(body, &out); err != nil {
		return nil, fmt.Errorf("orthanc 응답을 못 읽는다: %w", err)
	}
	// Orthanc 는 이미 있는 인스턴스에도 200 + Status:AlreadyStored 를 낸다.
	// 이것도 중복이므로 같이 잡는다.
	if out.Status == "AlreadyStored" {
		return &out, ErrDuplicate
	}
	return &out, nil
}

func (c *Client) Healthy(ctx context.Context) error {
	req, _ := http.NewRequestWithContext(ctx, http.MethodGet, c.Base+"/system", nil)
	if c.User != "" {
		req.SetBasicAuth(c.User, c.Pass)
	}
	res, err := c.HTTP.Do(req)
	if err != nil {
		return err
	}
	defer res.Body.Close()
	io.Copy(io.Discard, io.LimitReader(res.Body, 4096))
	if res.StatusCode != 200 {
		return fmt.Errorf("orthanc %d", res.StatusCode)
	}
	return nil
}
