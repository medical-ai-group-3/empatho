package storage

import (
	"context"
	"errors"
	"io"
	"mime"
	"os"
	"path/filepath"
	"strings"
)

// FS — 로컬 디스크. 시험과 개발용이다.
//
// ⚠ 키를 그대로 경로로 쓰므로 ".." 를 막아야 한다. 게이트웨이가 키를
//
//	티켓에서만 만들지만, 저장소 단에서도 한 번 더 막는다 — 한 겹으로
//	막는 것은 언젠가 뚫린다.
type FS struct{ Root string }

func NewFS(root string) *FS { return &FS{Root: root} }

func (f *FS) Bucket() string { return "local:" + f.Root }

var errBadKey = errors.New("잘못된 object_key")

func (f *FS) path(key string) (string, error) {
	if key == "" || strings.Contains(key, "..") || strings.HasPrefix(key, "/") {
		return "", errBadKey
	}
	p := filepath.Join(f.Root, filepath.FromSlash(key))
	// Join 이 정규화한 뒤에도 뿌리 안인지 확인한다
	root, err := filepath.Abs(f.Root)
	if err != nil {
		return "", err
	}
	abs, err := filepath.Abs(p)
	if err != nil {
		return "", err
	}
	if !strings.HasPrefix(abs, root+string(os.PathSeparator)) {
		return "", errBadKey
	}
	return abs, nil
}

func (f *FS) Put(ctx context.Context, key string, r io.Reader, size int64, ct string) error {
	p, err := f.path(key)
	if err != nil {
		return err
	}
	if err := os.MkdirAll(filepath.Dir(p), 0o755); err != nil {
		return err
	}
	tmp := p + ".part"
	fh, err := os.Create(tmp)
	if err != nil {
		return err
	}
	if _, err := io.Copy(fh, r); err != nil {
		fh.Close()
		os.Remove(tmp)
		return err
	}
	if err := fh.Close(); err != nil {
		os.Remove(tmp)
		return err
	}
	// 원자적 교체 — 중간 상태의 파일이 보이지 않게 한다
	return os.Rename(tmp, p)
}

func (f *FS) Open(ctx context.Context, key string) (ReadSeekCloser, *Info, error) {
	p, err := f.path(key)
	if err != nil {
		return nil, nil, err
	}
	fh, err := os.Open(p)
	if err != nil {
		return nil, nil, err
	}
	st, err := fh.Stat()
	if err != nil {
		fh.Close()
		return nil, nil, err
	}
	return fh, &Info{Key: key, Size: st.Size(), ModTime: st.ModTime(),
		ContentType: guessType(key)}, nil
}

func (f *FS) Stat(ctx context.Context, key string) (*Info, error) {
	p, err := f.path(key)
	if err != nil {
		return nil, err
	}
	st, err := os.Stat(p)
	if err != nil {
		return nil, err
	}
	return &Info{Key: key, Size: st.Size(), ModTime: st.ModTime(),
		ContentType: guessType(key)}, nil
}

func (f *FS) Delete(ctx context.Context, key string) error {
	p, err := f.path(key)
	if err != nil {
		return err
	}
	return os.Remove(p)
}

func guessType(key string) string {
	if t := mime.TypeByExtension(filepath.Ext(key)); t != "" {
		return t
	}
	return "application/octet-stream"
}
