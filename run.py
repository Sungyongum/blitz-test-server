from Blitz_app import create_app
from Blitz_app.extensions import db
from Blitz_app.models import User
from Blitz_app.models.trade import Trade

app = create_app()

# Flask Shell에서 자동으로 로딩되도록 설정
@app.shell_context_processor
def make_shell_context():
    return {
        'db': db,
        'User': User,
        'Trade': Trade
    }

if __name__ == '__main__':
    with app.app_context():
        db.create_all()
    app.run(host='0.0.0.0', port=8000)
