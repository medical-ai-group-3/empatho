package hub

import (
	"fmt"
	"runtime"
	"sync"
	"testing"
	"time"
)

func ev(id string) Event { return Event{ID: id, Type: "report_ready"} }

func TestPublishReachesAllConnectionsOfOneUser(t *testing.T) {
	h := New(4)
	a, ca := h.Subscribe("u1")
	defer ca()
	b, cb := h.Subscribe("u1") // 같은 사람이 창을 두 개 열었다
	defer cb()

	if n := h.Publish("u1", ev("N1")); n != 2 {
		t.Fatalf("연결 2개인데 %d개로 갔다", n)
	}
	for i, s := range []*Sub{a, b} {
		select {
		case got := <-s.C:
			if got.ID != "N1" {
				t.Errorf("연결 %d: %q", i, got.ID)
			}
		default:
			t.Errorf("연결 %d 가 못 받았다", i)
		}
	}
}

// 남의 알림이 가면 안 된다. 여기가 새면 다른 환자 판독 결과가 남에게 뜬다.
func TestPublishDoesNotLeakAcrossUsers(t *testing.T) {
	h := New(4)
	a, ca := h.Subscribe("u1")
	defer ca()
	b, cb := h.Subscribe("u2")
	defer cb()

	h.Publish("u1", ev("N1"))
	select {
	case got := <-b.C:
		t.Fatalf("u2 가 u1 알림을 받았다: %q", got.ID)
	default:
	}
	if len(a.C) != 1 {
		t.Errorf("u1 이 못 받았다")
	}
}

func TestPublishToNobody(t *testing.T) {
	h := New(4)
	if n := h.Publish("없는사람", ev("N1")); n != 0 {
		t.Errorf("구독자가 없는데 %d", n)
	}
}

// ★ 이 시험이 이 패키지의 이유다.
//
// 안 읽는 구독자가 하나 있으면 나머지가 다 막히는지 본다. 순서대로
// 차단 전송을 하면 여기서 영원히 멈춘다.
func TestSlowSubscriberDoesNotBlockOthers(t *testing.T) {
	h := New(2) // 버퍼 2 — 금방 찬다
	slow, cs := h.Subscribe("u1")
	defer cs()
	fast, cf := h.Subscribe("u1")
	defer cf()

	done := make(chan int, 1)
	go func() {
		n := 0
		for i := 0; i < 50; i++ {
			n += h.Publish("u1", ev(fmt.Sprintf("N%d", i)))
		}
		done <- n
	}()

	// fast 는 계속 읽는다. slow 는 한 글자도 안 읽는다.
	go func() {
		for {
			select {
			case <-fast.C:
			case <-fast.Done():
				return
			}
		}
	}()

	select {
	case <-done:
	case <-time.After(3 * time.Second):
		t.Fatal("느린 구독자 하나에 발행이 막혔다 — 알림 체계 전체가 선다")
	}
	_ = slow
	if h.Lagging.Load() == 0 {
		t.Error("버려진 것이 없다고 나온다 — 밀림을 안 세고 있다")
	}
}

// 버린 알림을 **조용히** 버리면 안 된다. 잃었다는 사실은 남아야 한다.
func TestLaggedFlagIsSetAndClearsOnce(t *testing.T) {
	h := New(1)
	s, c := h.Subscribe("u1")
	defer c()

	h.Publish("u1", ev("N1")) // 버퍼에 들어간다
	h.Publish("u1", ev("N2")) // 넘친다
	if !s.Lagged() {
		t.Fatal("넘쳤는데 표시가 안 됐다 — 알림이 조용히 사라진다")
	}
	// 한 번 읽으면 지워져야 한다. 안 지우면 resync 가 매번 나간다.
	if s.Lagged() {
		t.Error("Lagged 가 안 지워진다")
	}
}

// 구독을 닫으면 맵에서 빠져야 한다. 안 빠지면 연결마다 메모리가 샌다.
func TestUnsubscribeRemoves(t *testing.T) {
	h := New(4)
	_, c1 := h.Subscribe("u1")
	_, c2 := h.Subscribe("u1")
	if u, n := h.Stats(); u != 1 || n != 2 {
		t.Fatalf("stats = %d/%d", u, n)
	}
	c1()
	if u, n := h.Stats(); u != 1 || n != 1 {
		t.Fatalf("하나 닫은 뒤 stats = %d/%d", u, n)
	}
	c2()
	if u, n := h.Stats(); u != 0 || n != 0 {
		t.Fatalf("전부 닫은 뒤 stats = %d/%d — 사용자 항목이 남았다", u, n)
	}
	c1() // 두 번 불러도 죽으면 안 된다 (defer 와 명시 호출이 겹칠 수 있다)
	c2()
}

// 연결이 계속 열리고 닫히는 동안 발행이 돌아도 멀쩡해야 한다.
//
// ⚠ 이 시험은 "닫힌 채널에 보내기" 를 **잡지 못한다.** 실제로 확인했다 —
//
//	잠금 밖에서 close 하도록 일부러 망가뜨리고 세 번 돌렸는데 세 번 다
//	통과했다. 겹치는 창이 너무 좁아서 우연에 기댄다.
//	그래서 그 사고는 시험이 아니라 **설계로** 막았다. C 를 아무도 안 닫고
//	done 을 대신 닫는다 (hub.go 의 Sub 주석). 이 시험은 잠금이 걸린 채로
//	교착이 나거나 구독이 맵에 남는지를 보는 그물이다.
func TestConcurrentPublishAndUnsubscribe(t *testing.T) {
	h := New(64)
	var pub, subs sync.WaitGroup
	const rounds = 3000

	for i := 0; i < 4; i++ {
		pub.Add(1)
		go func() {
			defer pub.Done()
			for j := 0; j < rounds; j++ {
				h.Publish("u1", ev("N"))
			}
		}()
	}
	for i := 0; i < 4; i++ {
		subs.Add(1)
		go func() {
			defer subs.Done()
			for j := 0; j < rounds; j++ {
				s, c := h.Subscribe("u1")
				runtime.Gosched() // 발행이 이 연결을 집을 틈을 준다
				select {          // 비차단 — 발행이 끝나도 안 걸린다
				case <-s.C:
				default:
				}
				c()
			}
		}()
	}
	pub.Wait()
	subs.Wait()
	if u, n := h.Stats(); u != 0 || n != 0 {
		t.Errorf("전부 닫았는데 %d명/%d연결이 남았다", u, n)
	}
}

func TestConcurrentReadersAndPublishers(t *testing.T) {
	h := New(8)
	var wg sync.WaitGroup
	for u := 0; u < 5; u++ {
		user := fmt.Sprintf("u%d", u)
		s, c := h.Subscribe(user)
		wg.Add(1)
		go func() {
			defer wg.Done()
			defer c()
			for i := 0; i < 20; i++ {
				select {
				case <-s.C:
				case <-time.After(2 * time.Second):
					return
				}
			}
		}()
		wg.Add(1)
		go func() {
			defer wg.Done()
			for i := 0; i < 20; i++ {
				h.Publish(user, ev("N"))
			}
		}()
	}
	wg.Wait()
	if h.Published.Load() != 100 {
		t.Errorf("발행 수 = %d (100 이어야 한다)", h.Published.Load())
	}
}
