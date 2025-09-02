# Blitz_app/concurrency_guard.py
"""
Enhanced concurrency guard for SimpleBotManager operations
"""

import threading
import time
from typing import Dict, Set
from collections import defaultdict

class UserConcurrencyGuard:
    """
    Per-user concurrency guard to ensure bot operations serialize per user
    while allowing cross-user parallelism.
    """
    
    def __init__(self):
        self._user_locks: Dict[int, threading.Lock] = {}
        self._in_flight_operations: Dict[int, Set[str]] = defaultdict(set)
        self._global_lock = threading.Lock()
    
    def get_user_lock(self, user_id: int) -> threading.Lock:
        """Get or create a lock for the user"""
        with self._global_lock:
            if user_id not in self._user_locks:
                self._user_locks[user_id] = threading.Lock()
            return self._user_locks[user_id]
    
    def is_operation_in_flight(self, user_id: int, operation: str) -> bool:
        """Check if an operation is already in flight for the user"""
        with self._global_lock:
            return operation in self._in_flight_operations[user_id]
    
    def mark_operation_start(self, user_id: int, operation: str):
        """Mark operation as started for the user"""
        with self._global_lock:
            self._in_flight_operations[user_id].add(operation)
    
    def mark_operation_complete(self, user_id: int, operation: str):
        """Mark operation as completed for the user"""
        with self._global_lock:
            self._in_flight_operations[user_id].discard(operation)
            # Clean up empty sets
            if not self._in_flight_operations[user_id]:
                del self._in_flight_operations[user_id]
    
    def get_stats(self) -> dict:
        """Get concurrency statistics"""
        with self._global_lock:
            return {
                'active_users': len(self._in_flight_operations),
                'total_operations': sum(len(ops) for ops in self._in_flight_operations.values()),
                'operations_by_user': dict(self._in_flight_operations)
            }

class ConcurrencyContext:
    """Context manager for bot operations with concurrency control"""
    
    def __init__(self, guard: UserConcurrencyGuard, user_id: int, operation: str, timeout: float = 30.0):
        self.guard = guard
        self.user_id = user_id
        self.operation = operation
        self.timeout = timeout
        self.acquired = False
        self.user_lock = None
    
    def __enter__(self):
        # Check if operation already in flight
        if self.guard.is_operation_in_flight(self.user_id, self.operation):
            raise ConcurrencyError(f"Operation {self.operation} already in flight for user {self.user_id}")
        
        # Get user lock
        self.user_lock = self.guard.get_user_lock(self.user_id)
        
        # Try to acquire lock with timeout
        if self.user_lock.acquire(timeout=self.timeout):
            self.acquired = True
            self.guard.mark_operation_start(self.user_id, self.operation)
            return self
        else:
            raise ConcurrencyError(f"Could not acquire lock for user {self.user_id} within {self.timeout}s")
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        if self.acquired:
            self.guard.mark_operation_complete(self.user_id, self.operation)
            self.user_lock.release()

class ConcurrencyError(Exception):
    """Exception raised when concurrency limits are exceeded"""
    pass

# Global instance
_concurrency_guard = UserConcurrencyGuard()

def get_concurrency_guard() -> UserConcurrencyGuard:
    """Get the global concurrency guard instance"""
    return _concurrency_guard

def with_user_concurrency(operation: str, timeout: float = 30.0):
    """Decorator to add per-user concurrency control to bot operations"""
    def decorator(func):
        def wrapper(self, user_id: int, *args, **kwargs):
            guard = get_concurrency_guard()
            try:
                with ConcurrencyContext(guard, user_id, operation, timeout):
                    return func(self, user_id, *args, **kwargs)
            except ConcurrencyError as e:
                return {
                    "success": False,
                    "message": str(e),
                    "status": "concurrency_error",
                    "retry_after": 30
                }
        return wrapper
    return decorator