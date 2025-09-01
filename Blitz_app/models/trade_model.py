# Blitz_app/models/trade_model.py

from Blitz_app.extensions import db

class Trade(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    symbol = db.Column(db.String(50))
    side = db.Column(db.String(10))
    entry_price = db.Column(db.Float)
    exit_price = db.Column(db.Float)
    pnl = db.Column(db.Float)
    timestamp = db.Column(db.DateTime)
