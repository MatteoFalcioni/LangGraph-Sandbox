# repl_server.py
import io, traceback, asyncio
from contextlib import redirect_stdout
from fastapi import FastAPI
from pydantic import BaseModel

# FastAPI 'bridge' between the host and the Python REPL in the container's memory

app = FastAPI()

# One long-lived namespace => variables persist across calls
GLOBAL_NS = {"__name__": "__main__"}

class ExecRequest(BaseModel):
    code: str
    timeout: int | None = 120  # seconds

@app.get("/health")
def health():
    return {"ok": True}

@app.post("/exec")
async def exec_code(req: ExecRequest):
    out = io.StringIO()
    try:
        # Optional: simple timeout guard
        async def run():
            with redirect_stdout(out):
                # Use one shared dict -> state persists
                exec(req.code, GLOBAL_NS, GLOBAL_NS)
        await asyncio.wait_for(run(), timeout=req.timeout or 120)
        return {"ok": True, "stdout": out.getvalue()}
    except asyncio.TimeoutError:
        return {"ok": False, "stdout": out.getvalue(), "error": "Execution timed out."}
    except Exception:
        return {"ok": False, "stdout": out.getvalue(), "error": traceback.format_exc()}
