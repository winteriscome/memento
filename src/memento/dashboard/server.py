"""FastAPI application and server launcher."""
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

from memento.dashboard.routes import router

STATIC_DIR = Path(__file__).parent / "static"


def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""
    app = FastAPI(title="Memento Dashboard", version="0.1.0")
    app.include_router(router)

    # Serve static files (Vue SPA)
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

    @app.get("/")
    async def index():
        return FileResponse(str(STATIC_DIR / "index.html"))

    return app


def run_server(port: int = 8230, open_browser: bool = True):
    """Start the dashboard server."""
    import uvicorn
    import webbrowser
    import threading

    url = f"http://localhost:{port}"

    if open_browser:
        def _open():
            import time
            time.sleep(1)
            webbrowser.open(url)
        threading.Thread(target=_open, daemon=True).start()

    print(f"🧠 Memento Dashboard: {url}")
    print("   Press Ctrl+C to stop.")
    uvicorn.run(
        create_app(),
        host="127.0.0.1",
        port=port,
        log_level="warning",
    )
