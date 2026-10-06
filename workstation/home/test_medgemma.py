import io
import msgpack
import requests
from PIL import Image

img = Image.new("RGB", (64, 64), color=(200, 150, 150))
buf = io.BytesIO()
img.save(buf, format="PNG")

body = msgpack.packb({
    "job_id": "test-medgemma-1",
    "system": "당신은 유방암 병리를 판독하는 전문의입니다. 한 문장으로만 답하세요.",
    "text": "이 이미지는 테스트용 단색 이미지입니다. 짧게 아무 말이나 해주세요.",
    "image": buf.getvalue(),
    "max_new_tokens": 100,
}, use_bin_type=True)

resp = requests.post(
    "http://localhost:8000/medgemma",
    data=body,
    headers={"Content-Type": "application/msgpack"},
    timeout=120,
)
print("상태 코드:", resp.status_code)
result = msgpack.unpackb(resp.content, raw=False)
print("생성된 텍스트:", result["generated_text"])
