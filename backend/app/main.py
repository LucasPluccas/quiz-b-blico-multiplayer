from fastapi import FastAPI
from fastapi.responses import JSONResponse

app = FastAPI(title="Quiz Bíblico Multiplayer")

@app.get("/health")
def health():
    return JSONResponse({"status": "ok"})
