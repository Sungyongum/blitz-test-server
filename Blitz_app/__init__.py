# Blitz_app/__init__.py

from flask import Flask, redirect, url_for, flash
from flask_login import current_user
from flask_admin import Admin, AdminIndexView
from flask_admin.contrib.sqla import ModelView
from flask_migrate import Migrate
from flask_wtf.csrf import CSRFProtect
from werkzeug.security import generate_password_hash
from datetime import datetime
from flask_session import Session
from redis import from_url
from .extensions import db, login_manager
from .models import User, Trade, BotCommand, BotEvent, UserBot, OrderPlan, PnlSnapshot
from .routes import main
from .api_routes import api
from .models.proxy_model import Proxy



# ✅ 함수 정의 먼저
def datetimeformat(value):
    try:
        return datetime.fromtimestamp(value / 1000).strftime('%Y-%m-%d %H:%M:%S')
    except:
        return str(value)

def create_app():
    app = Flask(__name__, template_folder='../templates', static_folder='../static')
    app.config.from_pyfile('config.py')

    # Initialize CSRF protection
    csrf = CSRFProtect(app)
    
    # Make CSRF token available in templates
    @app.context_processor
    def inject_csrf_token():
        from flask_wtf.csrf import generate_csrf
        return dict(csrf_token=generate_csrf())

    # 🔗 Session 초기화 (Redis 불가용시 filesystem 사용)
    if app.config.get("SESSION_TYPE", "").lower() == "redis":
        try:
            redis_url = app.config.get("SESSION_REDIS_URL", "redis://127.0.0.1:6379/0")
            app.config["SESSION_REDIS"] = from_url(redis_url, decode_responses=False)
        except Exception as e:
            # Redis 연결 실패시 filesystem으로 fallback
            print(f"⚠️ Redis 연결 실패, filesystem 세션으로 변경: {e}")
            app.config["SESSION_TYPE"] = "filesystem"
            app.config["SESSION_FILE_DIR"] = app.config.get("SESSION_FILE_DIR", "./instance/flask_session")

    Session(app)

    db.init_app(app)

    def register_models():
        _= User, Trade, Proxy, BotCommand, BotEvent, UserBot, OrderPlan, PnlSnapshot
    register_models()

    migrate = Migrate(app, db)

    login_manager.login_view = 'main.login'
    login_manager.init_app(app)
    app.register_blueprint(main)
    app.register_blueprint(api)
    
    # Register SimpleBotManager API routes
    from .api_bot_routes import api_bot
    app.register_blueprint(api_bot)
    
    # Initialize SimpleBotManager 
    from simple_bot_manager import init_simple_bot_manager
    init_simple_bot_manager(app)
    

    # 🔐 관리자 접근 제한 Mixin
    class AdminAccessMixin:
        def is_accessible(self):
            return current_user.is_authenticated and current_user.email == 'admin@admin.com'

        def inaccessible_callback(self, name, **kwargs):
            flash("접근 권한이 없습니다.", "danger")
            return redirect(url_for('main.index'))

    class SecureModelView(AdminAccessMixin, ModelView):
        can_create = False
        column_list = ('email', 'api_key', 'api_secret', 'telegram_token', 'symbol', 'side', 'leverage', 'repeat')
        form_columns = ('email', 'api_key', 'api_secret', 'telegram_token', 'telegram_chat_id',
                        'uid', 'symbol', 'side', 'take_profit', 'stop_loss',
                        'leverage', 'rounds', 'repeat', 'skip_uid_check')
    class SecureAdminIndexView(AdminAccessMixin, AdminIndexView): pass
    print("✅ Flask 앱 생성 완료 및 Admin 인터페이스 설정됨")



    admin = Admin(app, name='Blitz Admin', template_mode='bootstrap4', index_view=SecureAdminIndexView(url='/admin_ui'))
    admin.add_view(SecureModelView(User, db.session))

    class ProxyModelView(AdminAccessMixin, ModelView):
        column_list = ('ip', 'port', 'username', 'password', 'assigned_user_id')
        form_columns = ('ip', 'port', 'username', 'password', 'assigned_user_id')

    admin.add_view(ProxyModelView(Proxy, db.session))  # ✅ 이렇게 바꿔야 함

    # ✅ Jinja 필터 등록
    app.add_template_filter(datetimeformat, 'datetimeformat')

    with app.app_context():
        db.create_all()

        if not User.query.filter_by(email='admin@admin.com').first():
            admin_user = User(
                email='admin@admin.com',
                telegram_token='ADMIN_TELEGRAM_TOKEN',
                telegram_chat_id='000000000',
                api_key='API_KEY_PLACEHOLDER',
                api_secret='API_SECRET_PLACEHOLDER',                
                uid='ADMIN_UID',
                symbol='BTC/USDT',
                side='long',
                take_profit='1%',
                stop_loss='0%',
                leverage=1,
                rounds=1,
                repeat=False,
                grids=[],
                verification_token=None,
                skip_uid_check=True
            )
            admin_user.set_password('djatjddyd86')
            db.session.add(admin_user)
            db.session.commit()
            print("✅ admin@admin.com 계정 자동 생성 완료")

    return app
