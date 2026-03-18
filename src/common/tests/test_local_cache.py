import pytest
import time
from unittest.mock import patch
from src.common.local_cache import (
    lc_get,
    lc_set,
    lc_delete,
    lc_delete_prefix,
    lc_clear,
    lc_size
)

class TestLocalCache:

    def setup_method(self):
        """Ensure a clean slate before every test."""
        lc_clear()

    # ===========================================================================
    # 1. BASIC CRUD
    # ===========================================================================
    def test_set_and_get(self):
        lc_set("user_1", {"name": "Alex"}, ttl=10)
        assert lc_get("user_1") == {"name": "Alex"}
        assert lc_size() == 1

    def test_get_non_existent(self):
        assert lc_get("ghost_key") is None

    def test_delete(self):
        lc_set("to_del", "data")
        lc_delete("to_del")
        assert lc_get("to_del") is None
        assert lc_size() == 0

    def test_clear(self):
        lc_set("k1", 1)
        lc_set("k2", 2)
        lc_clear()
        assert lc_size() == 0

    # ===========================================================================
    # 2. TTL & EXPIRATION (Fast-forwarding Time)
    # ===========================================================================
    def test_expiration_logic(self):
        # Freeze time at 100.0
        with patch("time.monotonic", return_value=100.0):
            lc_set("expiring_soon", "secret", ttl=5) # Should expire at 105.0
            
            # Still valid at 104.9
            with patch("time.monotonic", return_value=104.9):
                assert lc_get("expiring_soon") == "secret"

            # Expired at 105.1
            with patch("time.monotonic", return_value=105.1):
                assert lc_get("expiring_soon") is None
                # Check that lazy eviction actually removed it from the dict
                assert lc_size() == 0

    # ===========================================================================
    # 3. PREFIX INVALIDATION
    # ===========================================================================
    def test_delete_prefix(self):
        lc_set("dash:stats", 1)
        lc_set("dash:leaderboard", 2)
        lc_set("user:profile", 3)

        lc_delete_prefix("dash:")

        assert lc_size() == 1
        assert lc_get("user:profile") == 3
        assert lc_get("dash:stats") is None
        assert lc_get("dash:leaderboard") is None

    def test_delete_prefix_no_match(self):
        lc_set("keep:me", "data")
        lc_delete_prefix("non_existent:")
        assert lc_size() == 1
        assert lc_get("keep:me") == "data"