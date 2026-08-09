from __future__ import annotations

import unittest

from pymongo.errors import NetworkTimeout

from app.db.mongodb import MongoDatabaseManager


class _TrackingCollection:
    def __init__(self, *, fail_on_create: bool = False) -> None:
        self.fail_on_create = fail_on_create
        self.updated = False
        self.dropped = False
        self.created = False

    def update_many(self, *_args, **_kwargs) -> None:
        self.updated = True

    def drop_index(self, _name: str) -> None:
        self.dropped = True

    def create_index(self, *_args, **_kwargs) -> None:
        if self.fail_on_create:
            raise NetworkTimeout("timed out creating index")
        self.created = True


class _MongoDatabaseManagerUnderTest(MongoDatabaseManager):
    def __init__(self, collection: _TrackingCollection) -> None:
        super().__init__()
        self._collection = collection

    def wallet_ledger_entries_collection(self) -> _TrackingCollection:  # type: ignore[override]
        return self._collection

    def grocery_payment_attempts_collection(self) -> _TrackingCollection:  # type: ignore[override]
        return self._collection


class MongoDatabaseManagerTests(unittest.TestCase):
    def test_wallet_ledger_idempotency_index_is_created(self) -> None:
        collection = _TrackingCollection()
        manager = _MongoDatabaseManagerUnderTest(collection)

        manager._ensure_wallet_ledger_idempotency_index()

        self.assertTrue(collection.updated)
        self.assertTrue(collection.dropped)
        self.assertTrue(collection.created)

    def test_wallet_ledger_idempotency_index_timeout_is_swallowed(self) -> None:
        collection = _TrackingCollection(fail_on_create=True)
        manager = _MongoDatabaseManagerUnderTest(collection)

        manager._ensure_wallet_ledger_idempotency_index()

        self.assertTrue(collection.updated)
        self.assertTrue(collection.dropped)
        self.assertFalse(collection.created)

    def test_grocery_payment_attempt_provider_intent_index_is_created(self) -> None:
        collection = _TrackingCollection()
        manager = _MongoDatabaseManagerUnderTest(collection)

        manager._ensure_grocery_payment_attempt_provider_intent_index()

        self.assertTrue(collection.updated)
        self.assertTrue(collection.dropped)
        self.assertTrue(collection.created)

    def test_grocery_payment_attempt_provider_intent_index_timeout_is_swallowed(self) -> None:
        collection = _TrackingCollection(fail_on_create=True)
        manager = _MongoDatabaseManagerUnderTest(collection)

        manager._ensure_grocery_payment_attempt_provider_intent_index()

        self.assertTrue(collection.updated)
        self.assertTrue(collection.dropped)
        self.assertFalse(collection.created)


if __name__ == "__main__":
    unittest.main()
