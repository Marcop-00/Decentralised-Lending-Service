"""Persistent event inbox and transaction outbox for the two local services.

The cursor and discovered events are committed in one SQLite transaction. A
signed transaction is stored before broadcasting, so a retry/restart rebroadcasts
the same transaction instead of paying twice. No private keys are stored here.
These services target the professor's single-node private chain (no reorgs).
"""

import json
import sqlite3
from pathlib import Path


class PermanentEventError(RuntimeError):
    """An event cannot be served anymore; keep its reason for inspection."""


class EventStore:
    def __init__(self, path, identity, start_block=0):
        if start_block < 0:
            raise ValueError("Deployment block must be non-negative")
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(str(path))
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS events (
                id TEXT PRIMARY KEY, block_number INTEGER NOT NULL,
                payload TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'pending',
                attempts INTEGER NOT NULL DEFAULT 0, last_error TEXT,
                raw_tx TEXT, tx_hash TEXT
            );
        """)
        previous = self.db.execute("SELECT value FROM metadata WHERE key='identity'").fetchone()
        if previous and previous[0] != identity:
            self.db.close()
            raise ValueError("Event database belongs to another chain, contract or account")
        with self.db:
            self.db.execute("INSERT OR IGNORE INTO metadata VALUES ('identity', ?)", (identity,))
            self.db.execute("INSERT OR IGNORE INTO metadata VALUES ('next_block', ?)", (str(start_block),))

    @property
    def next_block(self):
        return int(self.db.execute("SELECT value FROM metadata WHERE key='next_block'").fetchone()[0])

    @property
    def checkpoint_hash(self):
        row = self.db.execute("SELECT value FROM metadata WHERE key='checkpoint_hash'").fetchone()
        return row[0] if row else None

    def enqueue_scan(self, events, through_block, block_hash=None):
        """Durably enqueue *all* decoded logs before moving the scan cursor."""
        with self.db:
            for event_id, block_number, payload in events:
                self.db.execute(
                    "INSERT OR IGNORE INTO events(id, block_number, payload) VALUES (?, ?, ?)",
                    (event_id, block_number, json.dumps(payload)),
                )
            self.db.execute("UPDATE metadata SET value=? WHERE key='next_block'", (str(through_block + 1),))
            if block_hash is not None:
                self.db.execute("INSERT OR REPLACE INTO metadata VALUES ('checkpoint_hash', ?)", (block_hash,))

    def pending(self):
        return list(self.db.execute("SELECT * FROM events WHERE status='pending' ORDER BY block_number, rowid"))

    def get(self, event_id):
        return self.db.execute("SELECT * FROM events WHERE id=?", (event_id,)).fetchone()

    def save_transaction(self, event_id, raw_tx, tx_hash):
        with self.db:
            self.db.execute("UPDATE events SET raw_tx=?, tx_hash=? WHERE id=?", (raw_tx, tx_hash, event_id))

    def clear_transaction(self, event_id):
        with self.db:
            self.db.execute("UPDATE events SET raw_tx=NULL, tx_hash=NULL WHERE id=?", (event_id,))

    def complete(self, event_id, reason=None, permanent=False):
        with self.db:
            self.db.execute("UPDATE events SET status=?, last_error=? WHERE id=?",
                            ("dead" if permanent else "done", reason, event_id))

    def retry(self, event_id, error):
        with self.db:
            self.db.execute("UPDATE events SET attempts=attempts+1, last_error=? WHERE id=?",
                            (str(error), event_id))

    def close(self):
        self.db.close()


def checked_receipt(receipt):
    if int(receipt["status"]) != 1:
        raise RuntimeError(f"Transaction reverted: {receipt.get('transactionHash', '<unknown>')}")
    return receipt


def make_web3(rpc_url):
    """The supplied genesis uses Clique, whose extraData exceeds 32 bytes."""
    from web3 import Web3
    from web3.middleware import ExtraDataToPOAMiddleware
    w3 = Web3(Web3.HTTPProvider(rpc_url))
    w3.middleware_onion.inject(ExtraDataToPOAMiddleware, layer=0, name="course_poa")
    return w3


def require_local_chain(w3):
    if not w3.is_connected():
        raise RuntimeError("Cannot connect to the local Ethereum node")
    if w3.eth.chain_id != 202526:
        raise RuntimeError(f"Expected the course chain 202526, found {w3.eth.chain_id}")


def store_identity(w3, contract_address, account_address):
    genesis_hash = w3.eth.get_block(0)["hash"].hex()
    return f"{w3.eth.chain_id}:{genesis_hash}:{contract_address.lower()}:{account_address.lower()}"


def scan_events(w3, contract, event_name, signature, store, batch_size=1000):
    start = store.next_block
    head = w3.eth.block_number
    if head < start - 1:
        raise RuntimeError("Ethereum chain was reset behind the saved cursor; use the new deployment's database")
    if store.checkpoint_hash is not None:
        previous_hash = w3.to_hex(w3.eth.get_block(start - 1)["hash"])
        if previous_hash != store.checkpoint_hash:
            raise RuntimeError("Ethereum checkpoint changed: chain reset/reorganization; inspect the deployment before resuming")
    if start > head:
        return
    end = min(head, start + batch_size - 1)
    end_hash = w3.to_hex(w3.eth.get_block(end)["hash"])
    logs = w3.eth.get_logs({
        "address": contract.address,
        "topics": [w3.to_hex(w3.keccak(text=signature))],
        "fromBlock": start, "toBlock": end,
    })
    decoded = []
    for log in logs:
        event = getattr(contract.events, event_name)().process_log(log)
        event_id = f"{log['transactionHash'].hex()}:{log['logIndex']}"
        decoded.append((event_id, int(log["blockNumber"]), dict(event["args"])))
    if w3.to_hex(w3.eth.get_block(end)["hash"]) != end_hash:
        raise RuntimeError("Ethereum chain changed during event scan; cursor not advanced")
    store.enqueue_scan(decoded, end, end_hash)


def _known_receipt(w3, tx_hash):
    try:
        return w3.eth.get_transaction_receipt(tx_hash)
    except Exception as exc:
        if type(exc).__name__ == "TransactionNotFound":
            return None
        raise


def send_durable(w3, account, tx_call, store, event_id):
    row = store.get(event_id)
    if row["tx_hash"]:
        receipt = _known_receipt(w3, row["tx_hash"])
        if receipt is not None:
            if int(receipt["status"]) != 1:
                store.clear_transaction(event_id)
            return checked_receipt(receipt)
        raw_tx = bytes.fromhex(row["raw_tx"])
        tx_hash = row["tx_hash"]
    else:
        transaction = tx_call.build_transaction({
            "from": account.address,
            "nonce": w3.eth.get_transaction_count(account.address, "pending"),
            "gasPrice": w3.eth.gas_price,
            "chainId": w3.eth.chain_id,
        })
        raw_tx = bytes(account.sign_transaction(transaction).raw_transaction)
        tx_hash = w3.to_hex(w3.keccak(raw_tx))
        store.save_transaction(event_id, raw_tx.hex(), tx_hash)
    try:
        w3.eth.send_raw_transaction(raw_tx)
    except Exception as exc:
        # A previous process may have already sent/mined precisely this hash.
        if "nonce too low" in str(exc).lower():
            known = _known_receipt(w3, tx_hash)
            if known is None:
                raise PermanentEventError(
                    f"Nonce conflict for saved transaction {tx_hash}; another transaction may have consumed "
                    "the nonce. Inspect the outbox and chain before retrying; no replacement was sent."
                ) from exc
            if int(known["status"]) != 1:
                store.clear_transaction(event_id)
            return checked_receipt(known)
        if not any(reason in str(exc).lower() for reason in ("already known", "known transaction", "nonce too low")):
            raise
    receipt = w3.eth.wait_for_transaction_receipt(tx_hash, timeout=120)
    if int(receipt["status"]) != 1:
        store.clear_transaction(event_id)
    return checked_receipt(receipt)


def process_pending(store, handler, logger):
    for row in store.pending():
        try:
            handler(row["id"], json.loads(row["payload"]))
            store.complete(row["id"])
        except PermanentEventError as exc:
            store.complete(row["id"], str(exc), permanent=True)
            logger.error("Event %s cannot be served: %s", row["id"], exc)
        except Exception as exc:
            store.retry(row["id"], exc)
            logger.error("Event %s remains pending for retry: %s", row["id"], exc)
            # One account owns the outbox. Do not race its next nonce while an
            # earlier transaction may still be unconfirmed or unbroadcast.
            break
