# Blitz_app/pnl_service.py

import pytz
from datetime import datetime, date
from typing import Dict, List, Optional, Tuple
from collections import defaultdict
import json

from .extensions import db
from .models import User, Trade, PnlSnapshot
from .trade_log import load_trade_log

# Asia/Seoul timezone
SEOUL_TZ = pytz.timezone('Asia/Seoul')

class PnlService:
    """
    Service for handling PnL calculations and reporting with proper timezone handling.
    
    Features:
    - Exchange-reported gross PnL (pre-fee) extraction
    - Asia/Seoul timezone for accurate date handling
    - Daily aggregation and win-rate calculation
    - Fallback to manual calculation when exchange data unavailable
    """
    
    @staticmethod
    def get_seoul_date(timestamp: Optional[datetime] = None) -> date:
        """Get current date in Asia/Seoul timezone"""
        if timestamp is None:
            timestamp = datetime.utcnow()
        
        # Convert UTC to Seoul time
        utc_dt = timestamp.replace(tzinfo=pytz.UTC)
        seoul_dt = utc_dt.astimezone(SEOUL_TZ)
        return seoul_dt.date()
    
    @staticmethod
    def extract_exchange_pnl(trade_data: Dict) -> Optional[float]:
        """
        Extract exchange-reported gross PnL from trade data.
        
        Different exchanges use different field names:
        - Bybit: realizedPnl, execPnl
        - BingX: closedPnl, realizedPnl
        - Binance: realizedPnl
        """
        if not trade_data:
            return None
        
        # Common exchange PnL field names (prioritized by reliability)
        pnl_fields = [
            'realizedPnl',      # Most common
            'execPnl',          # Bybit execution PnL
            'closedPnl',        # BingX closed PnL
            'grossPnl',         # Some exchanges
            'pnl',              # Generic fallback
        ]
        
        for field in pnl_fields:
            value = trade_data.get(field)
            if value is not None:
                try:
                    return float(value)
                except (ValueError, TypeError):
                    continue
        
        # If no exchange PnL found, try to extract from info object
        info = trade_data.get('info', {})
        if info:
            for field in pnl_fields:
                value = info.get(field)
                if value is not None:
                    try:
                        return float(value)
                    except (ValueError, TypeError):
                        continue
        
        return None
    
    @staticmethod
    def calculate_gross_pnl_fallback(trade_data: Dict) -> Optional[float]:
        """
        Fallback calculation for gross PnL when exchange data unavailable.
        
        Gross PnL = (Exit Price - Entry Price) * Size * Direction
        """
        try:
            entry_price = trade_data.get('entry_price') or trade_data.get('entryPrice')
            exit_price = trade_data.get('exit_price') or trade_data.get('exitPrice') or trade_data.get('price')
            size = trade_data.get('size') or trade_data.get('amount') or trade_data.get('contracts')
            side = trade_data.get('side')
            
            if not all([entry_price, exit_price, size, side]):
                return None
            
            entry_price = float(entry_price)
            exit_price = float(exit_price)
            size = float(size)
            
            # Calculate direction multiplier
            direction = 1 if side.lower() in ['long', 'buy'] else -1
            
            # Gross PnL calculation (pre-fee)
            pnl = (exit_price - entry_price) * size * direction
            return round(pnl, 4)
            
        except (ValueError, TypeError, AttributeError):
            return None
    
    @staticmethod
    def get_user_trades_with_pnl(user_id: int) -> List[Dict]:
        """Get user trades with enhanced PnL data"""
        trades = []
        
        # Get trades from database
        db_trades = Trade.query.filter_by(user_id=user_id).all()
        for trade in db_trades:
            trade_data = {
                'id': trade.id,
                'user_id': trade.user_id,
                'symbol': trade.symbol,
                'side': trade.side,
                'entry_price': trade.price,  # Assuming price is entry price
                'size': trade.amount,
                'timestamp': trade.timestamp,
                'seoul_date': PnlService.get_seoul_date(trade.timestamp).strftime('%Y-%m-%d'),
                'exchange_pnl': None,
                'gross_pnl': trade.pnl or 0,
                'source': 'database'
            }
            trades.append(trade_data)
        
        # Get trades from trade log (more detailed)
        try:
            trade_log = load_trade_log()
            log_trades = trade_log.get('trades', [])
            
            for trade_data in log_trades:
                if trade_data.get('user_id') != user_id:
                    continue
                
                # Extract exchange PnL first
                exchange_pnl = PnlService.extract_exchange_pnl(trade_data)
                
                # Fallback to manual calculation if needed
                if exchange_pnl is None:
                    exchange_pnl = PnlService.calculate_gross_pnl_fallback(trade_data)
                
                # Get timestamp and convert to Seoul date
                timestamp = trade_data.get('timestamp')
                if isinstance(timestamp, (int, float)):
                    timestamp = datetime.fromtimestamp(timestamp / 1000 if timestamp > 1e10 else timestamp)
                elif isinstance(timestamp, str):
                    try:
                        timestamp = datetime.fromisoformat(timestamp.replace('Z', '+00:00'))
                    except:
                        timestamp = datetime.utcnow()
                else:
                    timestamp = datetime.utcnow()
                
                enhanced_trade = {
                    'user_id': user_id,
                    'symbol': trade_data.get('symbol', ''),
                    'side': trade_data.get('side', ''),
                    'entry_price': trade_data.get('entry_price') or trade_data.get('entryPrice'),
                    'exit_price': trade_data.get('exit_price') or trade_data.get('exitPrice'),
                    'size': trade_data.get('size') or trade_data.get('amount'),
                    'timestamp': timestamp,
                    'seoul_date': PnlService.get_seoul_date(timestamp).strftime('%Y-%m-%d'),
                    'exchange_pnl': exchange_pnl,
                    'gross_pnl': exchange_pnl or trade_data.get('pnl', 0),
                    'source': 'trade_log'
                }
                trades.append(enhanced_trade)
                
        except Exception as e:
            print(f"Error loading trade log: {e}")
        
        # Sort by timestamp
        trades.sort(key=lambda x: x['timestamp'], reverse=True)
        return trades
    
    @staticmethod
    def aggregate_daily_pnl(user_id: int, update_snapshots: bool = True) -> List[Dict]:
        """
        Aggregate trades into daily PnL data for Asia/Seoul timezone.
        
        Returns list of daily aggregations and optionally updates pnl_snapshots table.
        """
        trades = PnlService.get_user_trades_with_pnl(user_id)
        
        # Group by Seoul date
        daily_data = defaultdict(lambda: {
            'date': None,
            'gross_pnl': 0.0,
            'wins': 0,
            'losses': 0,
            'trades': 0,
            'win_rate': 0.0
        })
        
        for trade in trades:
            seoul_date = trade['seoul_date']
            pnl = trade['gross_pnl']
            
            if pnl is None:
                continue
            
            daily_data[seoul_date]['date'] = seoul_date
            daily_data[seoul_date]['gross_pnl'] += float(pnl)
            daily_data[seoul_date]['trades'] += 1
            
            if float(pnl) > 0:
                daily_data[seoul_date]['wins'] += 1
            elif float(pnl) < 0:
                daily_data[seoul_date]['losses'] += 1
        
        # Calculate win rates and format
        result = []
        for date_str, data in daily_data.items():
            total_trades = data['wins'] + data['losses']
            data['win_rate'] = (data['wins'] / total_trades * 100) if total_trades > 0 else 0
            data['gross_pnl'] = round(data['gross_pnl'], 2)
            result.append(data)
        
        # Sort by date
        result.sort(key=lambda x: x['date'], reverse=True)
        
        # Update snapshots if requested
        if update_snapshots:
            PnlService.update_pnl_snapshots(user_id, result)
        
        return result
    
    @staticmethod
    def update_pnl_snapshots(user_id: int, daily_data: List[Dict]):
        """Update or create PnL snapshots in database"""
        try:
            for data in daily_data:
                date_obj = datetime.strptime(data['date'], '%Y-%m-%d').date()
                
                # Check if snapshot exists
                snapshot = PnlSnapshot.query.filter_by(
                    user_id=user_id,
                    date=date_obj
                ).first()
                
                if snapshot:
                    # Update existing
                    snapshot.gross_pnl = data['gross_pnl']
                    snapshot.wins = data['wins']
                    snapshot.losses = data['losses']
                    snapshot.trades = data['trades']
                else:
                    # Create new
                    snapshot = PnlSnapshot(
                        user_id=user_id,
                        date=date_obj,
                        gross_pnl=data['gross_pnl'],
                        wins=data['wins'],
                        losses=data['losses'],
                        trades=data['trades']
                    )
                    db.session.add(snapshot)
            
            db.session.commit()
            
        except Exception as e:
            db.session.rollback()
            print(f"Error updating PnL snapshots: {e}")
    
    @staticmethod
    def get_user_pnl_summary(user_id: int) -> Dict:
        """Get comprehensive PnL summary for user"""
        daily_data = PnlService.aggregate_daily_pnl(user_id, update_snapshots=True)
        
        # Calculate totals
        total_pnl = sum(day['gross_pnl'] for day in daily_data)
        total_wins = sum(day['wins'] for day in daily_data)
        total_losses = sum(day['losses'] for day in daily_data)
        total_trades = total_wins + total_losses
        overall_win_rate = (total_wins / total_trades * 100) if total_trades > 0 else 0
        
        # Get recent performance (last 7 days)
        recent_data = daily_data[:7] if len(daily_data) >= 7 else daily_data
        recent_pnl = sum(day['gross_pnl'] for day in recent_data)
        
        # Find best and worst days
        best_day = max(daily_data, key=lambda x: x['gross_pnl']) if daily_data else None
        worst_day = min(daily_data, key=lambda x: x['gross_pnl']) if daily_data else None
        
        return {
            'user_id': user_id,
            'total_pnl': round(total_pnl, 2),
            'total_wins': total_wins,
            'total_losses': total_losses,
            'total_trades': total_trades,
            'overall_win_rate': round(overall_win_rate, 2),
            'recent_pnl_7d': round(recent_pnl, 2),
            'best_day': best_day,
            'worst_day': worst_day,
            'daily_data': daily_data,
            'last_updated': datetime.utcnow().isoformat(),
            'timezone': 'Asia/Seoul'
        }
    
    @staticmethod
    def get_all_users_pnl_summary() -> List[Dict]:
        """Get PnL summary for all users"""
        users = User.query.all()
        summaries = []
        
        for user in users:
            try:
                summary = PnlService.get_user_pnl_summary(user.id)
                summary['email'] = user.email
                summaries.append(summary)
            except Exception as e:
                print(f"Error getting PnL for user {user.id}: {e}")
                summaries.append({
                    'user_id': user.id,
                    'email': user.email,
                    'total_pnl': 0,
                    'error': str(e)
                })
        
        return summaries

# Utility functions for timezone formatting
def format_seoul_datetime(dt: datetime, format_str: str = '%Y-%m-%d %H:%M:%S') -> str:
    """Format datetime in Asia/Seoul timezone"""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=pytz.UTC)
    seoul_dt = dt.astimezone(SEOUL_TZ)
    return seoul_dt.strftime(format_str)

def format_seoul_date(dt: datetime) -> str:
    """Format date in Asia/Seoul timezone as YYYY-MM-DD"""
    return format_seoul_datetime(dt, '%Y-%m-%d')

def get_current_seoul_date() -> str:
    """Get current date in Asia/Seoul as YYYY-MM-DD string"""
    return PnlService.get_seoul_date().strftime('%Y-%m-%d')