import os
from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from dotenv import load_dotenv

load_dotenv()

db = SQLAlchemy()


def create_app():
    app = Flask(__name__)
    app.config.from_mapping(
        SQLALCHEMY_DATABASE_URI=os.getenv('DATABASE_URL', 'sqlite:///planning.db'),
        SQLALCHEMY_TRACK_MODIFICATIONS=False,
    )
    db.init_app(app)

    with app.app_context():
        # import models so tables are registered
        from . import models
        db.create_all()

    # register blueprint
    from .api import bp as api_bp
    app.register_blueprint(api_bp, url_prefix='/api')

    @app.get('/health')
    def health():
        return {'ok': True}

    # serve a minimal snapshots page
    from flask import send_from_directory

    @app.get('/snapshots')
    def snapshots_page():
        static_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'static'))
        return send_from_directory(static_dir, 'snapshots.html')

    @app.get('/snapshots/<int:id>/view')
    def snapshot_view(id):
        static_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'static'))
        return send_from_directory(static_dir, 'snapshot_view.html')

    return app
