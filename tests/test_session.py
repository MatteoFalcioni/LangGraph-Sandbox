# tests/test_session.py
from session_manager import SessionManager
import os

# 1) start a session-pinned container
m = SessionManager(
    image="py-sandbox:latest",
    datasets_path=os.path.abspath("src/llm_data"),
    session_root="sessions",
)
sid = "conv"
print("Starting session:", sid)
m.start(sid)

# 2) First call: create a DF in RAM and an artifact on disk
code1 = r"""
import pandas as pd
from pathlib import Path

df = pd.DataFrame({"x":[1,2,3]})
print("DF created, len =", len(df))

# create an artifact
Path("/session/artifacts").mkdir(parents=True, exist_ok=True)
(Path("/session/artifacts/hello.txt")).write_text("hi from first call")
print("Wrote /session/artifacts/hello.txt")
"""
res1 = m.exec(sid, code1, timeout=30)
print("\n--- CALL 1 ---")
print("ok:", res1.get("ok"))
print("stdout:\n", res1.get("stdout"))
print("error:\n", res1.get("error"))
print("artifacts:", res1.get("artifact_map"))

# 3) Second call: reuse the same df (in RAM) and append another artifact
code2 = r"""
from pathlib import Path

# df should still exist in memory from previous call
print("describe:\n", df.describe())

# add another artifact
(Path("/session/artifacts/second.txt")).write_text("hello again")
print("Wrote /session/artifacts/second.txt")
"""
res2 = m.exec(sid, code2, timeout=30)
print("\n--- CALL 2 ---")
print("ok:", res2.get("ok"))
print("stdout:\n", res2.get("stdout"))
print("error:\n", res2.get("error"))
print("artifacts:", res2.get("artifact_map"))

print("\nSession dir on host:", res2.get("session_dir"))
print("Check files under:", os.path.join(res2.get("session_dir"), "artifacts"))

# Optional: stop the session at the end
# m.stop(sid)
