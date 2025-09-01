# Blitz_app/models/proxy_model.py

from Blitz_app.extensions import db

class Proxy(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    ip = db.Column(db.String(255), nullable=False)
    port = db.Column(db.Integer, nullable=False)  # ✅ 이 줄 추가
    username = db.Column(db.String(128), nullable=True)
    password = db.Column(db.String(128), nullable=True)
    assigned_user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)

    def __repr__(self):
        return f"<Proxy {self.ip}>"
