/* 켜고 끄는 스위치.
 *
 * 색만으로 말하지 않는다. **손잡이가 움직이는 것**이 켜짐/꺼짐을 지고,
 * 색은 거든다 — 앱 전체에서 지키는 규칙과 같다.
 *
 * role="switch" 를 붙인다. 그냥 button 이면 읽어 주는 기계가 «켜져 있음»을
 * 말해 주지 못하고, 사람은 눌러 보고서야 안다.
 */
export default function Switch({ on, onChange, label, disabled }) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={on}
      aria-label={label}
      disabled={disabled}
      className={on ? "sw on" : "sw"}
      onClick={() => onChange(!on)}
    >
      <i aria-hidden="true" />
    </button>
  );
}
