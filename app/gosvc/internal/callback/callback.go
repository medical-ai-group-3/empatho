// Package callback — 내부 콜백 (Go → Django). 명세 21장.
//
// Go 는 Postgres 에 직접 쓰지 않는다. 결과는 전부 이 통로로 Django 에 넘긴다.
//
// 인증   mTLS + X-Signature (HMAC-SHA256, 타임스탬프 + 본문)
// 멱등성 Idempotency-Key 필수 — 재시도가 중복 행을 만들면 안 된다
// 실패   지수 백오프 재시도
//
// ⚠ 콜백이 실패하면 "생성은 했는데 DB 에 없는" 상태가 된다. 그래서 재시도를
//
//	포기할 때 반드시 로그에 남긴다 — 조용히 삼키면 아무도 모른다.
package callback

import (
	"bytes"
	"context"
	"crypto/hmac"
	"crypto/sha256"
	"crypto/tls"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"io"
	"log"
	"math"
	"net/http"
	"strconv"
	"strings"
	"time"
)

type Client struct {
	Base    string // https://django-internal
	Secret  []byte // X-Signature 키
	HTTP    *http.Client
	Retries int
}

// New 는 mTLS 를 쓸 수 있으면 쓰고, 인증서가 없으면 경고하고 평문으로 간다.
// 개발 중에 막히지 않게 하기 위함이다 — 운영에서는 반드시 인증서를 넣어야 한다.
func New(base string, secret []byte, certFile, keyFile string, retries int) *Client {
	tr := &http.Transport{}
	if certFile != "" && keyFile != "" {
		cert, err := tls.LoadX509KeyPair(certFile, keyFile)
		if err != nil {
			log.Printf("[callback] ⚠ mTLS 인증서를 못 읽었다 (%v) — 평문으로 간다", err)
		} else {
			tr.TLSClientConfig = &tls.Config{Certificates: []tls.Certificate{cert}}
		}
	} else {
		log.Printf("[callback] ⚠ mTLS 인증서 경로가 비어 있다. 운영에서는 반드시 설정할 것")
	}
	return &Client{
		Base:    strings.TrimRight(base, "/"),
		Secret:  secret,
		HTTP:    &http.Client{Timeout: 20 * time.Second, Transport: tr},
		Retries: retries,
	}
}

// Narrative 는 I-4 로 보내는 본문이다. 명세 21장 I-4 행 그대로다.
type Narrative struct {
	NarrativeText      string   `json:"narrative_text"`
	EvidenceLinks      []string `json:"evidence_links"`
	DroppedSentenceLog []Drop   `json:"dropped_sentence_log"`
}

type Drop struct {
	Sentence string `json:"sentence"`
	Reason   string `json:"reason"`
}

// StorageObject 는 I-1 로 보내는 본문이다. 명세 21장 I-1 행 그대로다.
type StorageObject struct {
	Bucket         string `json:"bucket"`
	ObjectKey      string `json:"object_key"`
	ChecksumSHA256 string `json:"checksum_sha256"`
	ByteSize       int64  `json:"byte_size"`
	ContentType    string `json:"content_type"`
	StorageClass   string `json:"storage_class"`
	PatientID      string `json:"patient_id,omitempty"`
	ScopeID        string `json:"scope_id,omitempty"`
}

// PostStorageObject — I-1  POST /internal/v1/storage-objects
//
// 명세 21장 "순서 보장 — I-1 이 성공해야 I-2 가 유효하다". DICOM 메타(I-2)를
// 보내기 전에 이게 먼저 성공해야 한다.
//
// 멱등키는 object_key 로 잡는다. 같은 객체를 두 번 커밋해도 행이 하나여야 한다.
func (c *Client) PostStorageObject(ctx context.Context, o StorageObject) error {
	return c.post(ctx, "/internal/v1/storage-objects", "obj:"+o.ObjectKey, o)
}

// PostNarrative — I-4  POST /internal/v1/reports/{id}/narrative
//
// idemKey 는 같은 리포트에 대해 같은 값을 써야 한다. 재시도가 중복 행을
// 만들지 않게 하는 것이 목적이므로 요청마다 새로 만들면 의미가 없다.
func (c *Client) PostNarrative(ctx context.Context, reportID, idemKey string,
	n Narrative) error {
	return c.post(ctx, "/internal/v1/reports/"+reportID+"/narrative", idemKey, n)
}

func (c *Client) post(ctx context.Context, path, idemKey string, v any) error {
	body, err := json.Marshal(v)
	if err != nil {
		return err
	}
	var last error
	for attempt := 0; attempt <= c.Retries; attempt++ {
		if attempt > 0 {
			// 지수 백오프. 1s, 2s, 4s, 8s ...
			wait := time.Duration(math.Pow(2, float64(attempt-1))) * time.Second
			select {
			case <-ctx.Done():
				return fmt.Errorf("콜백 중단: %w", ctx.Err())
			case <-time.After(wait):
			}
		}
		err := c.once(ctx, path, idemKey, body)
		if err == nil {
			return nil
		}
		last = err
		// 4xx 는 다시 보내도 같다. 재시도하지 않는다.
		if strings.HasPrefix(err.Error(), "4") {
			break
		}
		log.Printf("[callback] %s 실패 (%d/%d): %v", path, attempt+1, c.Retries+1, err)
	}
	// 여기 도달하면 파일·생성물은 있는데 DB 에 없는 상태다. 반드시 남긴다.
	log.Printf("[callback] ✗ 최종 실패 %s idem=%s — DB 에 반영되지 않았다: %v",
		path, idemKey, last)
	return last
}

func (c *Client) once(ctx context.Context, path, idemKey string, body []byte) error {
	ts := strconv.FormatInt(time.Now().Unix(), 10)
	req, err := http.NewRequestWithContext(ctx, http.MethodPost, c.Base+path,
		bytes.NewReader(body))
	if err != nil {
		return err
	}
	req.Header.Set("Content-Type", "application/json")
	req.Header.Set("Idempotency-Key", idemKey)
	req.Header.Set("X-Timestamp", ts)
	req.Header.Set("X-Signature", Sign(c.Secret, ts, body))

	res, err := c.HTTP.Do(req)
	if err != nil {
		return err
	}
	defer res.Body.Close()
	io.Copy(io.Discard, io.LimitReader(res.Body, 4096))
	if res.StatusCode >= 200 && res.StatusCode < 300 {
		return nil
	}
	return fmt.Errorf("%d %s", res.StatusCode, res.Status)
}

// Sign — HMAC-SHA256(timestamp + "." + body). Django 쪽도 같은 식으로 계산해야 한다.
//
// ⚠ 팀과 맞출 것: 서명 대상 문자열의 조합 방식. 여기서는 "ts.body" 로 잇는다.
//
//	구분자 없이 이으면 (ts="1", body="23") 과 (ts="12", body="3") 이 같은
//	서명을 낸다 — 그래서 점을 넣었다.
func Sign(secret []byte, ts string, body []byte) string {
	m := hmac.New(sha256.New, secret)
	m.Write([]byte(ts))
	m.Write([]byte("."))
	m.Write(body)
	return hex.EncodeToString(m.Sum(nil))
}
