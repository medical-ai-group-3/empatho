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

// ErrNotFound - orthanc 에 없음, 조회 결과가 비었거나 404
var ErrNotFound = errors.New("ORTHANC_NOT_FOUND")

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

// Lookup — SOP Instance UID 로 Orthanc 인스턴스 ID 를 찾는다. POST /tools/lookup
//
// 없는 UID 에도 200 + [] 가 온다(2026-09-14 실물 확인). 그래서 빈 목록을 ErrNotFound 로 바꾼다.
// 같은 UID 가 시리즈·스터디에 걸릴 일은 없지만 Type 으로 인스턴스만 고른다.
func (c *Client) Lookup(ctx context.Context, sopUID string) (string, error) {
	req, err := http.NewRequestWithContext(ctx, http.MethodPost, c.Base+"/tools/lookup", strings.NewReader(sopUID))
	if err != nil {
		return "", err
	}
	req.Header.Set("Content-Type", "text/plain")
	if c.User != "" {
		req.SetBasicAuth(c.User, c.Pass)
	}
	res, err := c.HTTP.Do(req)
	if err != nil {
		return "", err
	}
	defer res.Body.Close()
	if res.StatusCode != http.StatusOK {
		return "", fmt.Errorf("orthanc lookup %d", res.StatusCode)
	}
	var hits []struct{ ID, Type string }
	if err := json.NewDecoder(io.LimitReader(res.Body, 1<<16)).Decode(&hits); err != nil {
		return "", fmt.Errorf("orthanc lookup 응답을 못 읽는다: %w", err)
	}
	for _, h := range hits {
		if h.Type == "Instance" {
			return h.ID, nil
		}
	}
	return "", ErrNotFound
}

// Get — GET 한 번. 본문을 흘려 받도록 응답을 그대로 돌려준다. Body 는 호출부가 닫는다.
//
//	/instances/{id}/file    DICOM 원본 한 장 (application/dicom)
//	/series/{id}/archive    시리즈 전체 zip (application/zip)
func (c *Client) Get(ctx context.Context, path string) (*http.Response, error) {
	req, err := http.NewRequestWithContext(ctx, http.MethodGet, c.Base+path, nil)
	if err != nil {
		return nil, err
	}
	if c.User != "" {
		req.SetBasicAuth(c.User, c.Pass)
	}
	res, err := c.HTTP.Do(req)
	if err != nil {
		return nil, err
	}
	if res.StatusCode == http.StatusNotFound {
		res.Body.Close()
		return nil, ErrNotFound
	}
	if res.StatusCode != http.StatusOK {
		res.Body.Close()
		return nil, fmt.Errorf("orthanc %d", res.StatusCode)
	}
	return res, nil
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
