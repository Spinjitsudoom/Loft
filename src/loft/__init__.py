"""Loft: a self-hosted ebook library."""


def main() -> None:
    import uvicorn

    from .app import create_app
    from .config import load_config

    cfg = load_config()
    cfg.data_dir.mkdir(parents=True, exist_ok=True)
    app = create_app(cfg)
    print(f"\n  Loft is running: open http://localhost:{cfg.port} in a browser"
          f" (on other devices, use this computer's address and port {cfg.port}).\n"
          f"  Its data is kept in {cfg.data_dir}\n  Press Ctrl+C, or close this window, to stop it.\n", flush=True)
    uvicorn.run(app, host=cfg.host, port=cfg.port)
