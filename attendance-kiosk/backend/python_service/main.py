from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

# Small app that composes routers from the api package
app = FastAPI(title="Offline Kiosk Face Recognition")

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Import and include routers from the api package
from api import state, recognition, sync, session, outbox, media, students

app.include_router(recognition.router)
app.include_router(sync.router)
app.include_router(session.router)
app.include_router(outbox.router)
app.include_router(media.router)
app.include_router(students.router)


@app.get("/health")
def health_check():
    return {"ok": True}


@app.on_event("startup")
def _startup_load():
    # Load embeddings into memory at startup; don't crash the app if it fails
    try:
        state.load_embeddings()
    except Exception:
        pass


