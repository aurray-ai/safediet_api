from __future__ import annotations

import unittest

from app.models.billing import WalletLedgerDirection, WalletLedgerEntryType
from app.repositories.wallet_ledger_repository import WalletLedgerRepository


class CapturingCollection:
    def __init__(self) -> None:
        self.inserted: list[dict] = []

    def insert_one(self, document: dict) -> None:
        self.inserted.append(document)


class WalletLedgerRepositoryTests(unittest.TestCase):
    def test_create_entry_omits_null_idempotency_key(self) -> None:
        collection = CapturingCollection()
        repository = WalletLedgerRepository(collection)  # type: ignore[arg-type]

        entry = repository.create_entry(
            wallet_account_id="wallet-1",
            user_id="user-1",
            entry_type=WalletLedgerEntryType.TOPUP_CREDIT,
            direction=WalletLedgerDirection.CREDIT,
            amount_minor=2500,
            currency="GBP",
            reference_type="wallet_topup",
            reference_id="ref-1",
            funding_method=None,
            idempotency_key=None,
            metadata={"provider_mode": "sandbox"},
        )

        self.assertEqual(entry.idempotency_key, None)
        self.assertEqual(len(collection.inserted), 1)
        self.assertNotIn("idempotency_key", collection.inserted[0])


if __name__ == "__main__":
    unittest.main()
