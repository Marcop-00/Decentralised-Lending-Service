"""
auto_voter.py — Bot per la votazione automatica delle proposte di prestito.

Funzionamento:
1. Si collega al nodo locale (Hardhat).
2. Ascolta l'evento 'LoanProposed' emesso dal FundingPool.
3. Valuta i parametri del prestito (es. interesse e durata) usando una strategia predefinita.
4. Invia automaticamente la transazione di voto (Sì/No).
"""

import time
import json
import logging
import os
from web3 import Web3
from web3.exceptions import ContractLogicError
from dotenv import load_dotenv
load_dotenv(".env")

# ─── Configurazione Logging ──────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

# ─── Costanti e Parametri ────────────────────────────────────────────────────
RPC_URL = os.getenv("ETH_RPC_URL", "http://127.0.0.1:8545")
POOL_ADDRESS = os.getenv("POOL_ADDRESS")
VOTER_PRIVATE_KEY = os.getenv("VOTER_PRIVATE_KEY")
POLL_INTERVAL = 5 # Secondi tra un controllo e l'altro

# Strategia di voto (Personalizzabile)
MIN_INTEREST_BPS = 400  # Vota SI solo se l'interesse è almeno del 4%
MAX_DURATION_BLOCKS = 50000 # Rifiuta prestiti con durata superiore a ~7 giorni in blocchi

# Caricamento dinamico dell'ABI dal file compilato di Hardhat
# Assicurati che il percorso sia corretto rispetto a dove esegui lo script
ABI_PATH = os.path.join(
    os.path.dirname(__file__), 
    "../../artifacts/contracts/FundingPool.sol/FundingPool.json"
)

# ─── Funzione di Voto ────────────────────────────────────────────────────────
def evaluate_and_vote(pool_contract, voter_account, w3, proposal_id, principal, interest_bps, duration_blocks):
    """
    Valuta i parametri e invia la transazione di voto.
    """
    # 1. Logica di valutazione
    support = True
    reason = "Rispetta i requisiti di rischio."
    
    if interest_bps < MIN_INTEREST_BPS:
        support = False
        reason = f"Interesse troppo basso ({interest_bps} bps < {MIN_INTEREST_BPS})."
    elif duration_blocks > MAX_DURATION_BLOCKS:
        support = False
        reason = f"Durata troppo lunga ({duration_blocks} blocchi > {MAX_DURATION_BLOCKS})."

    vote_str = "SI" if support else "NO"
    logger.info(f"Valutazione Proposta #{proposal_id}: Voto {vote_str} -> {reason}")

    # 2. Creazione e invio transazione
    try:
        nonce = w3.eth.get_transaction_count(voter_account.address)
        
        tx = pool_contract.functions.voteOnProposal(proposal_id, support).build_transaction({
            "from": voter_account.address,
            "nonce": nonce,
            "gas": 200000,
            "gasPrice": w3.eth.gas_price,
        })
        
        signed_tx = voter_account.sign_transaction(tx)
        tx_hash = w3.eth.send_raw_transaction(signed_tx.raw_transaction)
        
        logger.info(f"Transazione di voto inviata! Hash: {tx_hash.hex()}")
        
        # Aspettiamo la conferma
        receipt = w3.eth.wait_for_transaction_receipt(tx_hash)
        status = "Successo" if receipt["status"] == 1 else "Fallita"
        logger.info(f"Voto registrato con {status} nel blocco {receipt['blockNumber']}")
        
    except ContractLogicError as e:
        logger.error(f"Errore logico del contratto durante il voto: {e}")
    except Exception as e:
        logger.error(f"Errore di rete/invio transazione: {e}")


# ─── Ciclo di Polling ────────────────────────────────────────────────────────
def run_polling_loop(pool_contract, voter_account, w3):
    """
    Scansiona continuamente i nuovi blocchi per intercettare l'evento 'LoanProposed'.
    """
    logger.info("=== AUTO-VOTER AVVIATO ===")
    logger.info(f"In ascolto sull'indirizzo Pool: {pool_contract.address}")
    logger.info(f"Account votante: {voter_account.address}")
    
    last_checked_block = w3.eth.block_number
    logger.info(f"Partenza dal blocco: {last_checked_block}")

    # Otteniamo la firma (topic) dell'evento per filtrarlo
    event_signature = w3.keccak(text="LoanProposed(uint256,address,string,uint256,uint256,uint256,uint256)").hex()

    while True:
        time.sleep(POLL_INTERVAL)
        try:
            current_block = w3.eth.block_number

            if current_block <= last_checked_block:
                continue

            # Cerchiamo i log tra l'ultimo blocco controllato e quello attuale
            logs = w3.eth.get_logs({
                "address": pool_contract.address,
                "topics": [event_signature],
                "fromBlock": last_checked_block + 1,
                "toBlock": current_block,
            })

            last_checked_block = current_block

            for log in logs:
                # Decodifichiamo l'evento usando web3.py
                event = pool_contract.events.LoanProposed().process_log(log)
                args = event["args"]
                
                proposal_id = args["proposalId"]
                borrower = args["borrower"]
                principal = args["principal"]
                interest_bps = args["interestBps"]
                duration_blocks = args["durationBlocks"]
                
                principal_eth = w3.from_wei(principal, 'ether')
                
                logger.info(f"--- NUOVA PROPOSTA RILEVATA ---")
                logger.info(f"ID: {proposal_id} | Da: {borrower}")
                logger.info(f"Richiesta: {principal_eth} ETH | Interesse: {interest_bps} bps | Durata: {duration_blocks} blocchi")
                
                evaluate_and_vote(pool_contract, voter_account, w3, proposal_id, principal, interest_bps, duration_blocks)

        except Exception as e:
            logger.error(f"Errore nel ciclo di polling: {e}. Riprovo tra {POLL_INTERVAL} secondi...")


# ─── Entry Point ─────────────────────────────────────────────────────────────
if __name__ == "__main__":
    w3 = Web3(Web3.HTTPProvider(RPC_URL))
    
    if not w3.is_connected():
        logger.error("Impossibile connettersi al nodo Ethereum. Assicurati che Hardhat sia in esecuzione.")
        exit(1)
        
    if POOL_ADDRESS == "0x..." or VOTER_PRIVATE_KEY == "0x...":
        logger.error("Devi configurare POOL_ADDRESS e VOTER_PRIVATE_KEY nello script o nel file .env!")
        exit(1)

    voter_account = w3.eth.account.from_key(VOTER_PRIVATE_KEY)
    
    with open(ABI_PATH) as f:
        pool_abi = json.load(f)["abi"]

    pool_contract = w3.eth.contract(
        address=Web3.to_checksum_address(POOL_ADDRESS),
        abi=pool_abi
    )

    run_polling_loop(pool_contract, voter_account, w3)