# Blitz_app/__init__.py

from flask import Flask, redirect, url_for, flash
from flask_login import current_user
from flask_admin import Admin, AdminIndexView
from flask_admin.contrib.sqla import ModelView
from flask_migrate import Migrate
from werkzeug.security import generate_password_hash
from datetime import datetime
from .extensions import db, login_manager
from .models import User, Trade, BotCommand, BotEvent, UserBot, OrderPlan, PnlSnapshot
from .routes import main
from .api_routes import api
from .lite_routes import lite
from .models.proxy_model import Proxy
from .simple_bot_manager import get_simple_bot_manager


# ✅ 함수 정의 먼저
def datetimeformat(value):
    try:
        return datetime.fromtimestamp(value / 1000).strftime('%Y-%m-%d %H:%M:%S')
    except:
        return str(value)

def create_app():
    app = Flask(__name__, template_folder='../templates', static_folder='../static')
    app.config.from_pyfile('config.py')

    # Print DB info at startup
    db_path = app.config.get('SQLALCHEMY_DATABASE_URI', '').replace('sqlite:///', '')
    print(f"✅ Lite Server starting with DB: {db_path}")

    db.init_app(app)

    def register_models():
        _= User, Trade, Proxy, BotCommand, BotEvent, UserBot, OrderPlan, PnlSnapshot
    register_models()

    migrate = Migrate(app, db)

    login_manager.login_view = 'main.login'
    login_manager.init_app(app)
    app.register_blueprint(main)
    app.register_blueprint(api)
    app.register_blueprint(lite)
    
    # Initialize SimpleBotManager
    get_simple_bot_manager(app)
    

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


    admin = Admin(app, name='Blitz Admin', template_mode='bootstrap4', index_view=SecureAdminIndexView(url='/admin_ui'))
    admin.add_view(SecureModelView(User, db.session))

    class ProxyModelView(AdminAccessMixin, ModelView):
        column_list = ('ip', 'port', 'username', 'password', 'assigned_user_id')
        form_columns = ('ip', 'port', 'username', 'password', 'assigned_user_id')

    admin.add_view(ProxyModelView(Proxy, db.session))

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
