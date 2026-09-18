// Package upload — 청크 업로드 조립. 명세 19-2 G-F1~G-F3.
//
//	WSI 는 수 GB 단위라 단일 POST 로 받을 수 없다.
//
// 조각을 디스크에 받아 두었다가 complete 에서 순서대로 이어 붙이고,
// 이어 붙이면서 sha256 을 계산해 저장소에 올린다.
//
// 왜 메모리에 안 모으나 — 수 GB 다. 조각을 메모리에 쌓으면 프로세스가 죽는다.
// 왜 이어 붙이며 해시하나 — 다 쓴 뒤 다시 읽으면 수 GB 를 두 번 읽는다.
package upload

import (
	"crypto/sha256"
	"encoding/hex"
	"errors"
	"fmt"
	"io"
	"os"
	"path/filepath"
	"sort"
	"strconv"
	"strings"
	"sync"
	"time"
)

var (
	ErrNotFound = errors.New("UPLOAD_NOT_FOUND")
	ErrTooBig   = errors.New("UPLOAD_TOO_LARGE")
	ErrBadPart  = errors.New("BAD_PART_NUMBER")
)

type Session struct {
	ID          string
	ObjectKey   string
	ContentType string
	MaxBytes    int64
	PatientID   string
	ScopeID     string
	Created     time.Time

	// 티켓 purpose. 개시한 쪽의 값을 담아 둔다.
	//
	// ⚠ 이 값은 담아만 두고 검사는 main.go 의 sameTicket 이 한다.
	//   여기서 막지 않는다. 예전 주석은 여기서 막는 것처럼 적혀 있었으나
	//   실제로 대조하는 코드가 없었다 (2026-09-16).
	Purpose string

	mu    sync.Mutex
	bytes int64
	parts map[int]int64 // 조각 번호 -> 크기
}

type Manager struct {
	dir string
	mu  sync.Mutex
	s   map[string]*Session
	ttl time.Duration
}

func NewManager(dir string, ttl time.Duration) (*Manager, error) {
	if err := os.MkdirAll(dir, 0o700); err != nil {
		return nil, err
	}
	return &Manager{dir: dir, s: map[string]*Session{}, ttl: ttl}, nil
}

func (m *Manager) Init(id, objectKey, contentType, patientID, scopeID,
	purpose string, maxBytes int64) *Session {
	s := &Session{ID: id, ObjectKey: objectKey, ContentType: contentType,
		MaxBytes: maxBytes, PatientID: patientID, ScopeID: scopeID,
		Purpose: purpose, Created: time.Now(), parts: map[int]int64{}}
	m.mu.Lock()
	m.s[id] = s
	m.mu.Unlock()
	return s
}

func (m *Manager) Get(id string) (*Session, bool) {
	m.mu.Lock()
	defer m.mu.Unlock()
	s, ok := m.s[id]
	return s, ok
}

func (m *Manager) partPath(id string, n int) (string, error) {
	// id 는 우리가 만든 16진수다. 그래도 경로로 쓰기 전에 검사한다.
	if id == "" || strings.ContainsAny(id, `/\.`) {
		return "", ErrNotFound
	}
	if n < 1 || n > 100000 {
		return "", ErrBadPart
	}
	return filepath.Join(m.dir, id, fmt.Sprintf("%06d.part", n)), nil
}

// WritePart — 같은 번호를 다시 보내면 덮어쓴다(개별 재시도 허용, 명세 G-F2).
func (m *Manager) WritePart(s *Session, n int, r io.Reader) (int64, error) {
	p, err := m.partPath(s.ID, n)
	if err != nil {
		return 0, err
	}
	if err := os.MkdirAll(filepath.Dir(p), 0o700); err != nil {
		return 0, err
	}
	fh, err := os.Create(p)
	if err != nil {
		return 0, err
	}
	defer fh.Close()

	s.mu.Lock()
	prev := s.parts[n]
	room := s.MaxBytes - (s.bytes - prev)
	s.mu.Unlock()
	if s.MaxBytes <= 0 {
		room = 1 << 62
	}
	// 상한을 넘기면 더 읽지 않는다. 다 받고 나서 재는 게 아니라 받으면서 막는다.
	n64, err := io.Copy(fh, io.LimitReader(r, room+1))
	if err != nil {
		os.Remove(p)
		return 0, err
	}
	if s.MaxBytes > 0 && n64 > room {
		os.Remove(p)
		return 0, ErrTooBig
	}
	s.mu.Lock()
	s.bytes = s.bytes - prev + n64
	s.parts[n] = n64
	s.mu.Unlock()
	return n64, nil
}

// Assemble — 조각을 번호순으로 이어 붙이며 sha256 을 계산하고, put 으로 넘긴다.
// put 은 스트림을 받아 저장소에 올린다.
func (m *Manager) Assemble(s *Session,
	put func(r io.Reader, size int64, contentType string) error) (string, int64, error) {

	s.mu.Lock()
	nums := make([]int, 0, len(s.parts))
	var total int64
	for n, sz := range s.parts {
		nums = append(nums, n)
		total += sz
	}
	s.mu.Unlock()
	if len(nums) == 0 {
		return "", 0, errors.New("조각이 없다")
	}
	sort.Ints(nums)
	// 번호가 1..N 으로 이어지는지 — 빠진 조각이 있으면 조용히 짧은 파일이 된다
	for i, n := range nums {
		if n != i+1 {
			return "", 0, fmt.Errorf("조각 번호가 이어지지 않는다: %d 다음이 %d",
				i+1, n)
		}
	}

	pr, pw := io.Pipe()
	h := sha256.New()
	go func() {
		defer pw.Close()
		mw := io.MultiWriter(pw, h)
		for _, n := range nums {
			p, err := m.partPath(s.ID, n)
			if err != nil {
				pw.CloseWithError(err)
				return
			}
			fh, err := os.Open(p)
			if err != nil {
				pw.CloseWithError(err)
				return
			}
			if _, err := io.Copy(mw, fh); err != nil {
				fh.Close()
				pw.CloseWithError(err)
				return
			}
			fh.Close()
		}
	}()
	if err := put(pr, total, s.ContentType); err != nil {
		pr.CloseWithError(err)
		return "", 0, err
	}
	return hex.EncodeToString(h.Sum(nil)), total, nil
}

// Cleanup — 조각 폴더를 지운다. complete 든 실패든 반드시 부른다.
func (m *Manager) Cleanup(id string) {
	m.mu.Lock()
	delete(m.s, id)
	m.mu.Unlock()
	if id != "" && !strings.ContainsAny(id, `/\.`) {
		os.RemoveAll(filepath.Join(m.dir, id))
	}
}

// Sweep — 버려진 세션 청소. 업로드를 시작하고 안 끝내면 조각이 남는다.
func (m *Manager) Sweep() int {
	m.mu.Lock()
	var dead []string
	for id, s := range m.s {
		if time.Since(s.Created) > m.ttl {
			dead = append(dead, id)
		}
	}
	m.mu.Unlock()
	for _, id := range dead {
		m.Cleanup(id)
	}
	return len(dead)
}

func ParsePart(s string) (int, error) {
	n, err := strconv.Atoi(s)
	if err != nil || n < 1 {
		return 0, ErrBadPart
	}
	return n, nil
}
