# Database Update Bug Fix

## Problem

The local SQLite database was not being updated when syncing from the Baby Tracker server for **existing users who are already in a group**.

## Root Cause

The `TransactionHandler` (which writes synced data to the local database) was only initialized in the `join_group()` method but NOT in the `login()` method.

**What happened:**
1. When a new user joins a group → `join_group()` is called → `transaction_handler` is initialized ✅
2. When an existing user logs in → `login()` is called → `transaction_handler` is **NOT** initialized ❌
3. When `sync_transactions()` runs, it checks `if self.transaction_handler and ...` (api.py:645)
4. If `transaction_handler` is `None`, transactions are silently skipped
5. Result: Data is fetched from server but never written to the local database

## The Fix

Added transaction handler initialization to the `login()` method in `api.py`:

```python
# Initialize transaction handler if we have a local database
if self.local_db and not self.transaction_handler:
    from .transaction import TransactionHandler
    self.transaction_handler = TransactionHandler(self.local_db)
    _LOGGER.info("Initialized transaction handler")
```

This ensures that both new users (via `join_group()`) and existing users (via `login()`) will have their local database properly updated when syncing.

## Testing

After restarting Home Assistant:
1. Your database should now be updated when data is synced from the server
2. Check the Home Assistant logs for: `"Initialized transaction handler"`
3. Use any service (e.g., add_formula) and then check the database to verify the data was written
