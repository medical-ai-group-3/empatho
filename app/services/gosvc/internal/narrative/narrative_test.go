package narrative

import "testing"

func TestDecimalNotSplit(t *testing.T) {
	// 소수점이 문장을 쪼개면 안 된다. 이걸로 실제 버그를 잡았다.
	r := Filter("우상방에 1.2cm 종괴가 있다 [[e:L1]]. 0.5mm 석회 [[e:L2]].",
		[]string{"L1", "L2"})
	if len(r.Dropped) != 0 {
		t.Fatalf("버려진 문장 %d건: %+v", len(r.Dropped), r.Dropped)
	}
	if r.Text != "우상방에 1.2cm 종괴가 있다. 0.5mm 석회." {
		t.Fatalf("got %q", r.Text)
	}
}

func TestDropsUncited(t *testing.T) {
	r := Filter("근거 있다 [[e:L1]]. 근거 없다. 지어냈다 [[e:L9]].", []string{"L1"})
	if len(r.Dropped) != 2 {
		t.Fatalf("버림 %d건: %+v", len(r.Dropped), r.Dropped)
	}
	if r.Text != "근거 있다." {
		t.Fatalf("got %q", r.Text)
	}
	if r.Dropped[1].Reason == r.Dropped[0].Reason {
		t.Error("버린 이유가 구분되지 않는다")
	}
}

func TestEmptyAllowedDropsAll(t *testing.T) {
	r := Filter("무엇이든 [[e:L1]].", nil)
	if r.Text != "" || len(r.Dropped) != 1 {
		t.Fatalf("근거 목록이 비면 전부 버려야 한다: %q %+v", r.Text, r.Dropped)
	}
}

func TestNewlineBoundary(t *testing.T) {
	r := Filter("첫 줄 [[e:A]]\n둘째 줄\n셋째 [[e:A]]", []string{"A"})
	if len(r.Dropped) != 1 {
		t.Fatalf("%+v", r.Dropped)
	}
}
