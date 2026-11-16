"""Alcove: a self-hosted ebook library."""


def main() -> None:
    import uvicorn

    from .app import create_app
    from .config import load_config

    cfg = load_config()
    cfg.data_dir.mkdir(parents=True, exist_ok=True)
    uvicorn.run(create_app(cfg), host=cfg.host, port=cfg.port)
