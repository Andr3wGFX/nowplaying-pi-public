import sys, os, json, time, threading
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "stubs"))
import _sandbox  # noqa: F401  (throwaway HOME -- must precede nowplaying)
from pathlib import Path
import nowplaying as np

np.CAPTURE_DIR.mkdir(parents=True, exist_ok=True)
for f in list(np.CAPTURE_DIR.glob("*.jpg")): f.unlink()
for f in (np.LEDGER, np.GDRIVE_TOKEN):
    if f.exists(): f.unlink()

from PIL import Image
for n in ("a", "b"):
    Image.new("RGB", (64, 48), (120, 60, 30)).save(np.CAPTURE_DIR / f"shot-{n}.jpg")

print("--- 1. no token file: must drain quietly, not crash ---")
t = threading.Thread(target=np.upload_worker, daemon=True); t.start()
np.queue_upload(np.CAPTURE_DIR / "shot-a.jpg")
time.sleep(0.5)
print("    thread alive:", t.is_alive(), "| ledger:", np.LEDGER.exists())

print("\n--- 2. with a token, uploads + records + survives failures ---")
np.GDRIVE_TOKEN.write_text(json.dumps({"refresh_token": "fake", "folder_id": "F1"}))
np.upload_q = __import__("queue").Queue()
np._access.update(token="tok", expires=time.monotonic() + 9999)

calls = {"n": 0, "bodies": []}
def fake_upload(path, cfg):
    calls["n"] += 1
    if calls["n"] == 1:
        raise RuntimeError("simulated network drop")
    calls["bodies"].append((path.name, cfg["folder_id"]))
    return "id-%d" % calls["n"]
np._upload_one = fake_upload

t2 = threading.Thread(target=np.upload_worker, daemon=True); t2.start()
time.sleep(7)                      # first attempt fails, 5 s backoff, then ok
print("    attempts:", calls["n"])
print("    uploaded:", calls["bodies"])
print("    ledger  :", sorted(json.loads(np.LEDGER.read_text())))

print("\n--- 3. multipart body is well-formed ---")
np._access.update(token="tok", expires=time.monotonic() + 9999)
captured = {}
class FakeResp:
    status_code = 200
    def raise_for_status(self): pass
    def json(self): return {"id": "xyz"}
def fake_post(url, **kw):
    captured.update(url=url, headers=kw.get("headers"), data=kw.get("data"))
    return FakeResp()
np.requests.post = fake_post
import importlib
np._upload_one.__globals__  # noqa
# restore the real function to test its body construction
exec(compile(open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "nowplaying.py")).read().split("def _upload_one")[1].split("def upload_worker")[0]
             .join(["def _upload_one", ""]), "<x>", "exec"), np.__dict__)
np._upload_one(np.CAPTURE_DIR / "shot-b.jpg", {"folder_id": "F9"})
body = captured["data"]
ct = captured["headers"]["Content-Type"]
b = ct.split("boundary=")[1]
print("    url ok        :", captured["url"].endswith("uploadType=multipart"))
print("    boundary parts:", body.count(f"--{b}".encode()), "(want 3)")
print("    metadata      :", json.loads(body.split(b"\r\n\r\n")[1].split(b"\r\n--")[0]))
print("    ends properly :", body.endswith(f"\r\n--{b}--\r\n".encode()))
print("    jpeg header   :", b"\xff\xd8" in body)
