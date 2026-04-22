from __future__ import annotations
import argparse
from flask import Flask
from .config import MAX_CONTENT_LENGTH, SECRET_KEY
from .routes import bp

def create_app() -> Flask:
    app = Flask(__name__, template_folder="templates", static_folder="static")
    app.config["MAX_CONTENT_LENGTH"] = MAX_CONTENT_LENGTH
    app.config["SECRET_KEY"] = SECRET_KEY
    app.register_blueprint(bp)
    return app

def main() -> None:
    parser = argparse.ArgumentParser(description="Run Collage Mobile Pro web app.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=5000)
    parser.add_argument("--debug", action="store_true")
    args = parser.parse_args()

    app = create_app()
    app.run(host=args.host, port=args.port, debug=args.debug)

if __name__ == "__main__":
    main()
