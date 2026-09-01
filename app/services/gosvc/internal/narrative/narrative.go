// Package narrative — 근거 없는 문장 버리기. 명세 19-4.
//
//	"근거 좌표가 붙지 않은 문장은 버린다. 버린 문장은 I-4 로 되돌려
//	 report.dropped_sentence_log 에 저장"
//
// 명세는 '버린다' 까지만 정하고 **표시 형식은 안 정했다.** 아래는 우리 쪽
// 결정이다 — 팀과 맞춰야 한다.
//
//	모델에게 문장 끝마다 [[e:<근거id>]] 를 붙이게 한다.
//	  "우상방에 1.2cm 종괴가 있다 [[e:L1]]."
//
// 검사는 두 단계다.
//
//	① 표시가 있는가
//	② 그 id 가 **우리가 넘긴 근거 목록 안에 있는가**
//
// ② 가 핵심이다. ① 만 보면 모델이 [[e:L9]] 같은 없는 근거를 지어내도
// 통과한다. 지어낸 인용은 근거 없는 문장보다 나쁘다 — 확인된 것처럼 보인다.
package narrative

import (
	"regexp"
	"strings"
)

var tagRe = regexp.MustCompile(`\[\[e:([A-Za-z0-9_.:-]+)\]\]`)

type Drop struct {
	Sentence string
	Reason   string
}

type Result struct {
	Text     string   // 살아남은 문장만 이은 것. 표시는 지웠다
	Evidence []string // 실제로 인용된 근거 id (중복 없이, 나온 순서)
	Dropped  []Drop
}

// Filter — allowed 는 우리가 프롬프트에 넣어 준 근거 id 집합이다.
// allowed 가 비면 검사를 못 하므로 **전부 버린다** — 통과시키지 않는다.
// 근거를 안 넘긴 채로 서술만 받는 것은 이 규칙의 취지에 어긋난다.
func Filter(raw string, allowed []string) Result {
	ok := make(map[string]bool, len(allowed))
	for _, a := range allowed {
		ok[a] = true
	}
	var (
		kept []string
		ev   []string
		seen = map[string]bool{}
		res  Result
	)
	for _, s := range sentences(raw) {
		trimmed := strings.TrimSpace(s)
		if trimmed == "" {
			continue
		}
		ids := tagRe.FindAllStringSubmatch(trimmed, -1)
		if len(ids) == 0 {
			res.Dropped = append(res.Dropped, Drop{trimmed, "근거 표시 없음"})
			continue
		}
		var good []string
		for _, m := range ids {
			if ok[m[1]] {
				good = append(good, m[1])
			}
		}
		if len(good) == 0 {
			res.Dropped = append(res.Dropped, Drop{trimmed,
				"인용한 근거 id 가 제공 목록에 없음 (지어낸 인용)"})
			continue
		}
		for _, g := range good {
			if !seen[g] {
				seen[g] = true
				ev = append(ev, g)
			}
		}
		// 표시는 사람이 읽을 문장에서 지운다. 근거는 evidence_links 로 따로 간다.
		clean := strings.TrimSpace(tagRe.ReplaceAllString(trimmed, ""))
		clean = strings.TrimSpace(strings.ReplaceAll(clean, " .", "."))
		if clean != "" {
			kept = append(kept, clean)
		}
	}
	res.Text = strings.TrimSpace(strings.Join(kept, " "))
	res.Evidence = ev
	return res
}

// sentences — 문장으로 자른다.
//
// ⚠ 정규식으로 [.!?] 에서 자르면 **소수점에서 잘린다.** 시험에서 실제로
//
//	"우상방에 1.2cm 종괴가 있다" 가 "우상방에 1." 과 "2cm 종괴가 있다" 로
//	쪼개졌고, 앞쪽은 근거 표시가 없어 통째로 버려졌다. 판독 서술은
//	1.2cm · 0.5mm 이 도처에 있으므로 측정값이 든 문장이 전부 깨진다.
//
//	Go 정규식(RE2)은 전후방탐색이 없어 "숫자 사이의 점은 빼고" 를 패턴으로
//	못 쓴다. 그래서 직접 훑는다 — 앞뒤가 모두 숫자인 점은 경계로 안 본다.
func sentences(raw string) []string {
	r := []rune(raw)
	var out []string
	start := 0
	for i := 0; i < len(r); i++ {
		c := r[i]
		if c == '\n' {
			if s := strings.TrimSpace(string(r[start : i+1])); s != "" {
				out = append(out, s)
			}
			start = i + 1
			continue
		}
		if c != '.' && c != '!' && c != '?' {
			continue
		}
		// 1.2 · 0.5 — 앞뒤가 숫자면 소수점이다. 문장 끝이 아니다.
		if c == '.' && i > 0 && i+1 < len(r) &&
			isDigit(r[i-1]) && isDigit(r[i+1]) {
			continue
		}
		// 연속된 마침표(...)는 한 번만 끊는다
		j := i
		for j+1 < len(r) && (r[j+1] == '.' || r[j+1] == '!' || r[j+1] == '?') {
			j++
		}
		if s := strings.TrimSpace(string(r[start : j+1])); s != "" {
			out = append(out, s)
		}
		start = j + 1
		i = j
	}
	if s := strings.TrimSpace(string(r[start:])); s != "" {
		out = append(out, s)
	}
	return out
}

func isDigit(c rune) bool { return c >= '0' && c <= '9' }
