# Decentralised Lending Service

Project for Peer-to-Peer Systems and Blockchains Lab 2025/26, trace 1.1.
Contributors pool ETH and vote on loans. A trusted Python oracle records liquidity
from the first **131,000 Bitcoin mainnet blocks**. BTC ownership is not proved and
BTC are not locked: this is the professor's didactic simplification.

## Architecture

- FundingPoolProxy holds protocol state and ETH; FundingPool provides UUPS logic.
- Each approved proposal creates a dedicated LoanContract.
- BitcoinOracle stores satoshi balances; its Python service indexes Bitcoin UTXOs.
- The Python voter always votes YES, including when its capital is entirely locked.
- Both services use a durable SQLite event inbox and signed transaction outbox.
- Python setup creates accounts and deploys; the Python demo interacts with Geth.

## Laboratory stack

Hardhat **3.18.1**, TypeScript **6.0.3**, **node:test**, **viem 2.57.3**.
Solidity **0.8.24**, optimizer 200 runs, **Berlin** compiler target and simulated
network. OpenZeppelin Contracts/Upgradeable **5.6.1**. Native Solidity unit and
fuzz tests complement the TypeScript integration tests.

Use a supported even-numbered Node release (22.13.0+), Python 3.10+ and the pinned
Geth **1.13.14** implementation of the course's Clique chain. Dependencies are
recorded in package-lock.json; setup uses npm ci.

## Install and test

Run from this project directory:

    ./setup.sh
    npm run typecheck
    npm test
    ./.venv/bin/python -m unittest discover -s python/tests -v
    npm run test:gas
    npm run test:coverage

Setup installs dependencies, compiles and obtains Geth. It does not start a chain
or deploy contracts. Hardhat tests use isolated simulated chains.
Gas profiling writes **docs/gas-measurements.json** from transaction receipts,
plus Hardhat statistics. Figures depend on hardfork, storage and contributor count.
Coverage runs exercise the same scenarios without overwriting gas measurements
with costs from instrumented bytecode. HTML coverage is saved in coverage/html.

## Validate Bitcoin data before the real demo

Supply decoded mainnet blk*.dat records containing the continuous chain from
genesis to height **130,999**. File names alone do not establish completeness.
If the source uses block-file obfuscation, export/decode it at the source first.

    ./.venv/bin/python python/oracle/check_data.py --data-dir bitcoin --summary

This offline command needs no Ethereum node, private keys or .env. A successful
JSON result has **valid: true** and lists funded example addresses and their loan
capacity. It checks genesis, connected block count, payload hashes and Merkle
roots. It is a trusted-data parser, not a full Bitcoin consensus node. The genesis
reward is excluded; subsequent outputs to the same address remain valid.

**Replacement data validated on 11 October 2026:** the seven blk*.dat files
contain a connected chain of 162,844 blocks. The offline replay successfully
validated the required first 131,000 blocks (heights 0–130,999), reconstructing
299,208 UTXOs and 153,986 address entries. Both local copies have identical SHA256
hashes. The earlier incomplete-data issue is resolved; see
docs/bitcoin-validation.json for the replay result. The full Geth demo remains
to be verified. The service still refuses incomplete data.

## Start the private chain

Terminal 1:

    cd private-chain
    ./geth --datadir=./data init project2526genesis.json
    ./geth --datadir=./data --keystore=./keystore --networkid=202526 \
      --http --http.addr=127.0.0.1 --http.port=8545 --http.api=eth,net,web3 \
      --mine --miner.etherbase=d278d247a52c550508ea2b2c9321d816238fb523 \
      --unlock d278d247a52c550508ea2b2c9321d816238fb523 \
      --password password.txt --allow-insecure-unlock --ipcdisable

Terminal 2, from the project root:

    ./.venv/bin/python python/setup.py

Python setup first recompiles ordinary bytecode, including after a coverage run.
The prefunded account transfers ETH only to newly generated accounts. The new
deployer deploys the oracle, implementation and initialized proxy. Setup checks
chain ID 202526, receipts, bytecode and initialization, then writes .env files
with restrictive permissions and **DEPLOYMENT_BLOCK**. Running it again creates
a separate deployment and new accounts.

## Services and demo

Start these in separate terminals from the project root:

    ./.venv/bin/python python/oracle/oracle_service.py
    ./.venv/bin/python python/voter/auto_voter.py

Select an address with sufficient capacity from the validated data summary:

    ./.venv/bin/python python/simulate.py --btc-address YOUR_VALIDATED_ADDRESS --principal 1

BTC_ADDRESS can alternatively be set in the demo environment. The demo waits for
a fresh oracle event, checks actual liquidity, proposes, waits for the configured
contributor's YES, resolves, repays in two installments and claims gains. All
receipt statuses are checked and balances/state are printed along the way.

Services resume scanning from deployment/the saved cursor. Event insertion and
cursor advancement are atomic. Pending requests survive restarts and failures;
signed bytes are saved before broadcast, so retries recover the same transaction.
Closed proposals and conflicting nonces are explicitly recorded for inspection.
A block-hash checkpoint detects chain resets, even if the chain has regrown.
This persistence targets the course private chain, without automatic reorg recovery.

SQLite files are named events-*.sqlite3; EVENT_DB_PATH can override their location.
Use separate databases for each service/deployment and dedicated signing accounts.
Do not delete a database to fix a temporary RPC outage. No private keys are stored
in these databases, although signed pending transactions are retained.

## Explicit protocol rules

- Deposits must exceed 100,000 wei. Disposable capital excludes locked funds,
  pending gains and compensation reserves.
- Eligibility to vote uses the entire current position, including locked capital.
  Weights are recalculated using disposable balances at resolution. Nonvoters
  count as NO and ties reject.
- **12 blocks is the minimum before resolution**; voting remains possible until
  the borrower resolves. The retained ABI name votingDeadlineBlock means the
  earliest resolution block, not expiry of the vote.
- Allocation is proportional across all contributors. Rounding is deducted from
  the actual principal disbursed, not assigned to an arbitrary participant.
- BTC liquidity must cover the request at 1 BTC = 30 ETH.
- Every installment includes principal and interest. With principal P, interest
  I = floor(P * rate / 100), and cumulative accepted payment C, the principal
  target is floor(C * P / (P + I)). Each payment applies differences between
  cumulative targets. Collateral rounding is cumulative too. Surplus beyond the
  whole debt goes to the compensation pool.
- Principal refunds follow descending **initial** loan shares; the higher
  numerical address wins ties. The merge-sorted order is stored once.
- Gains use initial proportional weights, enter pendingInterestGain separately
  from deposits and are withdrawn via claimInterestGain. Distribution dust enters
  compensation.
- Collateral is fixed per loan from the global value (initially 50%, bounded
  1–100%, plus/minus five points per failed/successful loan).
- Repayment in dueBlock is timely; later repayment records irreversible default.
  A valid compensation request records default even with zero available funds.
  A zero payment leaves the claim unchanged for retry after a refill.
- Compensation forfeits the same amount of future **principal** recovery; original
  interest weights remain. It never creates a second withdrawal claim.
- Termination requires no active loans and preserves recovery operations.

The installment split, minimum voting period and zero-compensation behavior are
documented interpretations of the trace's less explicit wording. Tests encode
these choices.

## Security, upgrades and scale

The reentrancy test attacks an intentionally unsafe **FundingPoolVulnerable**,
which inherits the real pool and overrides withdrawal with stale balance writes
after the external transfer. The same attacker cannot steal other deposits from
the correct pool. This variant is never used by setup.

FundingPoolV2 demonstrates an actual compatible implementation change. Only the
owner may upgrade; initialized state and outstanding positions are preserved.
Existing LoanContract instances are independent immutable deployments: upgrading
the pool does not change old loan repayment code. Use a fresh setup to demonstrate
the new rules. Repository changes have not upgraded any existing chain.

Empty contributor positions are removed and sorting is performed once per loan.
Operations still scale with active contributor count; unlimited participation
within the block gas limit is outside this didactic design.

## Files and submission

- contracts/: protocol, proxy, oracle, loan and ordering library.
- contracts/test/: native Solidity tests, compatible V2 and vulnerable variant.
- test/: TypeScript node:test/viem tests and deployment helper.
- python/: setup, demo, persistent event processing, oracle, voter and offline tests.
- private-chain/: genesis and Geth setup.
- docs/: report source/PDF and gas measurements.

To regenerate the report after profiling:

    python3 docs/render_gas_table.py
    cd docs
    latexmk -pdf -interaction=nonstopmode -halt-on-error report.tex

Before submission, run the complete Geth demo with valid Bitcoin data and prepare
the course ZIP with source, tests, configuration, lockfile, scripts and the report
(maximum five pages). Omit node_modules, .venv, .env, event databases and regenerable
Ethereum data. Make the exact Bitcoin snapshot available according to course rules.
