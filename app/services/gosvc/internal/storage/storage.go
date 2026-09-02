// Package storage — 객체 저장소. 운영은 Garage(S3 호환), 시험은 로컬 디스크.
//
// 인터페이스로 갈라 둔 이유 — 게이트웨이 로직(티켓 검증 · 청크 조립 ·
// 체크섬 · Range 응답)이 저장소 종류와 무관해야 시험할 수 있다.
// 로컬 구현이 있으면 Garage 를 안 띄우고도 전 경로를 태울 수 있다.
//
// Open 이 ReadSeekCloser 를 돌려주는 이유는 http.ServeContent 에 그대로
// 넘기기 위해서다. Range · If-Range · 다중 구간을 직접 짜면 반드시 틀린다.
package storage

import (
	"context"
	"io"
	"time"
)

type Info struct {
	Key         string
	Size        int64
	ContentType string
	ETag        string
	ModTime     time.Time
}

type ReadSeekCloser interface {
	io.Reader
	io.Seeker
	io.Closer
}

type Store interface {
	Put(ctx context.Context, key string, r io.Reader, size int64, contentType string) error
	Open(ctx context.Context, key string) (ReadSeekCloser, *Info, error)
	Stat(ctx context.Context, key string) (*Info, error)
	Delete(ctx context.Context, key string) error
	Bucket() string
}
