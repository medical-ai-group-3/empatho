// Package hub — 알림 구독자 관리와 팬아웃. 명세 19-3 G-N1~G-N5.
//
// 문제는 **느린 구독자**다.
//
// 한 사용자가 창을 여러 개 띄워 놓고 그중 하나가 응답을 안 읽으면, 그
// 연결로 보내는 쓰기가 막힌다. 팬아웃을 그냥 순서대로 돌면 그 하나 때문에
// 나머지 전원이 알림을 못 받는다. 판독 완료 알림이 한 사람 브라우저 탓에
// 병동 전체에서 안 뜨는 상황이 된다.
//
// 그래서 구독자마다 버퍼를 두고 **막히지 않게** 보낸다.
//
// 버퍼가 차면 어떻게 하는가 — 이게 설계에서 제일 중요한 결정이다.
//
//	버리고 세기만 하면 그 알림은 **조용히 사라진다.** 사용자는 판독이
//	끝난 줄 모른다. 그건 알림 체계가 없느니만 못하다.
//
//	그래서 버퍼가 차면 그 구독자를 '밀렸다' 로 표시하고 resync 를 보낸다.
//	화면은 그걸 받으면 Django 에서 목록을 다시 받아 간다. 개별 알림은
//	잃되 **잃었다는 사실은 안 잃는다.**
package hub

import (
	"encoding/json"
	"sync"
	"sync/atomic"
	"time"
)

type Event struct {
	ID        string          `json:"id"`
	Type      string          `json:"type"` // report_ready · study_uploaded ...
	Payload   json.RawMessage `json:"payload,omitempty"`
	CreatedAt time.Time       `json:"created_at"`
}

type Sub struct {
	UserID string
	C      chan Event

	// done 은 구독이 끝났음을 알린다.
	//
	// ⚠ **C 는 아무도 닫지 않는다.** 닫는 순간 "닫힌 채널에 보내기" 로
	//   프로세스가 통째로 죽을 수 있고, 그건 잠금을 아무리 조심해도
	//   리뷰로만 지켜지는 규칙이 된다. 대신 아무도 보내지 않는 done 을
	//   닫는다 — 닫기와 보내기가 서로 다른 채널이라 그 사고가 **구조적으로
	//   불가능해진다.** 읽는 쪽은 C 와 Done() 을 함께 select 한다.
	done chan struct{}

	lagged atomic.Bool
}

// Done — 구독이 끝나면 닫힌다. 스트림 루프가 이걸로 빠져나간다.
func (s *Sub) Done() <-chan struct{} { return s.done }

// Lagged — 버퍼가 넘쳐 알림을 잃었는가. 스트림이 이걸 보고 resync 를 낸다.
// 읽으면서 지운다 — resync 를 한 번만 보내기 위해서다.
func (s *Sub) Lagged() bool { return s.lagged.Swap(false) }

type Hub struct {
	mu   sync.RWMutex
	subs map[string]map[*Sub]struct{} // user_id -> 연결들
	buf  int

	Published atomic.Int64
	Delivered atomic.Int64
	Lagging   atomic.Int64
}

func New(buf int) *Hub {
	if buf <= 0 {
		buf = 32
	}
	return &Hub{subs: map[string]map[*Sub]struct{}{}, buf: buf}
}

// Subscribe — 구독을 연다. 돌려주는 함수를 **반드시** defer 로 불러야 한다.
// 안 부르면 연결이 끊겨도 맵에 남아 메모리가 샌다.
func (h *Hub) Subscribe(userID string) (*Sub, func()) {
	s := &Sub{UserID: userID, C: make(chan Event, h.buf),
		done: make(chan struct{})}
	h.mu.Lock()
	if h.subs[userID] == nil {
		h.subs[userID] = map[*Sub]struct{}{}
	}
	h.subs[userID][s] = struct{}{}
	h.mu.Unlock()

	var once sync.Once
	return s, func() {
		once.Do(func() {
			// ⚠ close 는 **반드시 쓰기 잠금 안에서** 한다.
			//   Publish 는 읽기 잠금을 쥔 채로만 보내므로, 둘은 겹칠 수
			//   없다. 잠금 밖에서 닫으면 보내는 중인 Publish 가 닫힌
			//   채널에 써서 프로세스가 패닉으로 죽는다.
			h.mu.Lock()
			if m := h.subs[userID]; m != nil {
				delete(m, s)
				if len(m) == 0 {
					delete(h.subs, userID)
				}
			}
			h.mu.Unlock()
			close(s.C)
		})
	}
}

// Publish — 한 사용자의 모든 연결로 보낸다. 보낸 연결 수를 돌려준다.
//
// **절대 막히지 않는다.** 느린 구독자는 lagged 로 표시만 하고 넘어간다.
func (h *Hub) Publish(userID string, ev Event) int {
	h.Published.Add(1)

	// 잠금을 쥔 채로 보낸다. 보내기가 비차단이라 오래 쥐지 않는다.
	h.mu.RLock()
	n := 0
	for s := range h.subs[userID] {
		select {
		case s.C <- ev:
			n++
		default:
			// 버퍼가 찼다. 이 알림은 못 보내지만 잃었다는 사실은 남긴다.
			s.lagged.Store(true)
			h.Lagging.Add(1)
		}
	}
	h.mu.RUnlock()

	h.Delivered.Add(int64(n))
	return n
}

// Stats — 운영 확인용
func (h *Hub) Stats() (users, conns int) {
	h.mu.RLock()
	defer h.mu.RUnlock()
	for _, m := range h.subs {
		users++
		conns += len(m)
	}
	return
}
