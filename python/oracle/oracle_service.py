import logging
import os
import sys
import time
from collections import defaultdict

from btc_utils import is_coinbase, parse_blocks, script_to_address
from dotenv import load_dotenv
from web3 import Web3

# ─── Logging ─────────────────────────────────────────────────────────────────
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s", datefmt="%H:%M:%S")
logger = logging.getLogger(__name__)

# ─── Constants ───────────────────────────────────────────────────────────────
MAX_BLOCKS    = 131_000
POLL_INTERVAL = 5

ORACLE_ABI = [
    {
        "name": "UpdateRequested",
        "type": "event",
        "anonymous": False,
        "inputs": [
            {"name": "btcAddress", "type": "string", "indexed": False},
            {"name": "requester",  "type": "address", "indexed": True},
            {"name": "fee",        "type": "uint256", "indexed": False},
        ],
    },
    {
        "name": "update",
        "type": "function",
        "stateMutability": "nonpayable",
        "inputs": [
            {"name": "btcAddress",       "type": "string"},
            {"name": "balanceInSatoshi", "type": "uint256"},
        ],
        "outputs": [],
    }
]

utxo_set: dict[tuple[str, int], tuple[str, int]] = {}
addr_utxos: dict[str, dict[tuple[str, int], int]] = defaultdict(dict)

# ─── UTXO helpers ────────────────────────────────────────────────────────────
def _add_utxo(txid: str, vout: int, address: str, satoshi: int) -> None:
    utxo_set[(txid, vout)] = (address, satoshi)
    addr_utxos[address][(txid, vout)] = satoshi

def _remove_utxo(txid: str, vout: int) -> None:
    entry = utxo_set.pop((txid, vout), None)
    if entry is not None:
        address, _ = entry
        addr_utxos[address].pop((txid, vout), None)
        if not addr_utxos[address]:
            del addr_utxos[address]

def process_block(block, block_height: int) -> None:
    from bitcoin.core import b2lx
    for tx in block.vtx:
        txid = b2lx(tx.GetTxid())
        if not is_coinbase(tx):
            for vin in tx.vin:
                spent_txid = b2lx(vin.prevout.hash)
                spent_vout = vin.prevout.n
                _remove_utxo(spent_txid, spent_vout)

        for i, vout in enumerate(tx.vout):
            address = script_to_address(vout.scriptPubKey)
            if address is None:
                continue
            _add_utxo(txid, i, address, vout.nValue)

def get_address_balance(btc_address: str) -> int:
    return sum(addr_utxos.get(btc_address, {}).values())

# ─── Phase 1: Bitcoin blockchain sync ────────────────────────────────────────
def sync_bitcoin_blocks(blk_dat_dir: str) -> None:
    logger.info("=== SYNC Bitcoin: reading first %d blocks ===", MAX_BLOCKS)
    blocks_processed = 0
    for block_height, block in parse_blocks(blk_dat_dir, max_blocks=MAX_BLOCKS):
        try:
            process_block(block, block_height)
            blocks_processed += 1
        except Exception:
            continue
        if blocks_processed % 10_000 == 0:
            logger.info("  Processed %6d blocks | UTXO set: %d entries", blocks_processed, len(utxo_set))
    logger.info("SYNC complete: %d blocks processed", blocks_processed)

# ─── Phase 2: Ethereum event polling ─────────────────────────────────────────
def run_polling_loop(oracle_contract, operator_account, w3: Web3) -> None:
    logger.info("=== POLLING loop started (interval: %ds) ===", POLL_INTERVAL)
    last_checked_block = w3.eth.block_number

    while True:
        time.sleep(POLL_INTERVAL)
        try:
            current_block = w3.eth.block_number
            if current_block <= last_checked_block:
                continue

            logs = w3.eth.get_logs({
                "address": oracle_contract.address,
                "topics": ["0x" + w3.keccak(text="UpdateRequested(string,address,uint256)").hex()],
                "fromBlock": last_checked_block + 1,
                "toBlock":   current_block,
            })
            last_checked_block = current_block

            for log in logs:
                event = oracle_contract.events.UpdateRequested().process_log(log)
                btc_address = event["args"]["btcAddress"]
                logger.info("UpdateRequested: btcAddress=%s", btc_address)
                
                # A missing address and an address with no unspent outputs are both
                # reported as zero.  Never manufacture collateral: the pool must
                # make its decision from the UTXO set built from Bitcoin blocks.
                balance = get_address_balance(btc_address)
                logger.info("  Balance: %d satoshi (%.8f BTC)", balance, balance / 1e8)
                
                send_update(oracle_contract, operator_account, w3, btc_address, balance)
        except Exception as exc:
            logger.error("Polling loop error: %s", exc)

def send_update(oracle_contract, operator_account, w3: Web3, btc_address: str, balance: int) -> None:
    try:
        operator_address = operator_account.address
        nonce = w3.eth.get_transaction_count(operator_address)
        tx = oracle_contract.functions.update(btc_address, balance).build_transaction({
            "from":     operator_address,
            "nonce":    nonce,
            "gas":      200_000,
            "gasPrice": w3.eth.gas_price,
        })
        signed = operator_account.sign_transaction(tx)
        tx_hash = w3.eth.send_raw_transaction(signed.raw_transaction)
        receipt = w3.eth.wait_for_transaction_receipt(tx_hash)
        logger.info("  update() sent: txHash=%s status=%s", tx_hash.hex(), "OK" if receipt["status"] == 1 else "FAILED")
    except Exception as exc:
        logger.error("  Error sending update(): %s", exc)

# ─── Entry point ──────────────────────────────────────────────────────────────
def main() -> None:
    load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))
    
    blk_dat_dir   = os.getenv("BLK_DAT_DIR", "../../bitcoin")
    if not os.path.isabs(blk_dat_dir):
        blk_dat_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), blk_dat_dir))
    eth_rpc_url   = os.getenv("ETH_RPC_URL", "http://127.0.0.1:8545")
    oracle_addr   = os.getenv("ORACLE_ADDRESS", "")
    operator_key  = os.getenv("OPERATOR_PRIVATE_KEY", "")

    if not oracle_addr:
        logger.error("ORACLE_ADDRESS not set in .env")
        sys.exit(1)

    w3 = Web3(Web3.HTTPProvider(eth_rpc_url))
    if not w3.is_connected():
        logger.error("Failed to connect to Web3 node")
        sys.exit(1)

    operator_account = w3.eth.account.from_key(operator_key)
    oracle_contract = w3.eth.contract(address=Web3.to_checksum_address(oracle_addr), abi=ORACLE_ABI)

    # A collateral oracle without the required source blocks would be misleading.
    # Refuse to publish values until the first 131,000 mainnet blocks are available.
    if not os.path.isdir(blk_dat_dir):
        logger.error("Bitcoin block directory not found: %s", blk_dat_dir)
        logger.error("Provide BLK_DAT_DIR containing blk*.dat for the first 131,000 Bitcoin mainnet blocks.")
        sys.exit(1)
    sync_bitcoin_blocks(blk_dat_dir)

    # Phase 2: Poll
    run_polling_loop(oracle_contract, operator_account, w3)

if __name__ == "__main__":
    main()
