/* 계정 승인 목록 — 일괄 단추는 고른 줄이 있을 때만 눌린다.
 *
 * 0건인데 눌리면 Django 가 「항목이 선택되지 않았습니다」로 되돌려 보낸다.
 * 고장은 아니지만 한 번 헛걸음을 시킨다 — 누를 수 없을 때는 누를 수 없게
 * 보이는 편이 낫다.
 *
 * ⚠ CSS 의 :has() 로는 여기까지 못 한다. 흐리게는 할 수 있어도 진짜
 *   disabled 가 아니라, 초점을 준 뒤 Enter 를 누르면 그대로 넘어간다.
 *
 * ⚠ 처음에 disabled 를 HTML 로 박지 않는다. 자바스크립트가 꺼져 있으면
 *   영영 못 누르게 된다 — 그때는 켜진 채로 두고 Django 의 안내에 맡긴다.
 *
 * actions.js 가 「모두 고르기」로 각 칸을 **코드로** 바꾸는데 그때는 change
 * 가 안 뜬다. 다만 고르개 자신의 change 는 뜨고 그 시점엔 이미 다 바뀌어
 * 있어서, 폼에서 change 를 받는 것으로 충분하다. click 은 「전체 N개
 * 고르기」 링크까지 덮으려고 같이 받는다.
 */
"use strict";
{
    function sync() {
        const form = document.getElementById("changelist-form");
        if (!form) {
            return;
        }
        const any = form.querySelector(".action-select:checked") !== null;
        form.querySelectorAll(".e-bulk").forEach(function (button) {
            button.disabled = !any;
        });
    }

    document.addEventListener("DOMContentLoaded", function () {
        const form = document.getElementById("changelist-form");
        if (!form) {
            return;
        }
        form.addEventListener("change", sync);
        form.addEventListener("click", sync);
        sync();
    });
}
