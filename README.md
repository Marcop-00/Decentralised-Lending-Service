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

The normal flow is: fund a contributor, request a Bitcoin balance, deposit ETH,
propose a loan, vote, resolve after at least 12 blocks, repay and claim interest.
If a loan expires unpaid, its contributors can request compensation instead.
The vulnerable contract, attacker and V2 are demonstrations for the tests; the
service setup deploys only the oracle, pool implementation and proxy.

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
Gas profiling writes **docs/gas-measurements.json** from transaction receipts
and prints Hardhat statistics. The JSON is the single source for the report's
gas table. Figures depend on hardfork, storage and contributor count.
Coverage runs exercise the same scenarios without overwriting gas measurements
with costs from instrumented bytecode. HTML coverage is saved in coverage/html.

### Read the results

All commands above run from the project root. After setup, tests need no running
Geth, oracle or voter, no service .env files, no keys and no real Bitcoin dataset.
Installation and uncached compiler downloads need internet access. Do not run
python/setup.py just to test: that script deploys a separate service on Geth.
The tests do not change balances or deployments on your existing private chain.

- `npm run typecheck`: contract build and TypeScript checks; successful exit with
  no errors. The type checker may finish silently.
- `npm test`: **34 passing**, comprising 4 native Solidity tests and 30
  Node.js/TypeScript tests in this version. One Solidity fuzz test uses 256
  generated inputs; these are not 256 additional tests. This run also includes
  gas profiling and rewrites docs/gas-measurements.json.
- Python unittest discovery: **Ran 49 tests**, then **OK**. Miniature temporary
  datasets and mocked services cover parsing, UTXOs, event recovery, voting,
  setup safeguards and demo accounting; they do not validate your real dataset.
- `npm run test:gas`: **1 passing** profiling test covering **20 scenarios**.
  Values are receipt gasUsed units, not ETH or the transaction gas limit.
- `npm run test:coverage`: **34 passing**, then line/statement coverage.
  Open coverage/html/index.html in a browser; this is contract coverage, not
  Python coverage. Coverage is not proof of correctness or security.

A test can pass by checking that an invalid transaction reverts. The reentrancy
test passes only if the deliberately vulnerable pool is drained and the normal
pool protects the honest contributor. Read the final summary: failed assertions,
FAIL/ERROR or a nonzero exit status indicate a problem. Counts refer to this
version and change if tests are added.

### Run a focused check

    npm test -- test/advanced_behaviors.test.ts
    npm test -- test/events_and_isolation.test.ts
    npm test -- test/reentrancy.test.ts
    npm test -- test/upgrade.test.ts
    npm test -- contracts/test/LoanContract.t.sol
    ./.venv/bin/python -m unittest discover -s python/tests -p 'test_demo_scenarios.py' -v

Choose the relevant command: these check default/refund/interest accounting,
event emitters/arguments and loan independence, reentrancy, upgrades, native loan
rules and six offline demo checks respectively. The event check covers the pool
proxy, oracle and loan contracts, including a compensation retry that must not
emit another default. The isolation check uses two borrowers and verifies that
repaying either loan leaves the other loan's terms, repayments and positions unchanged.
If a test fails, rerun its file and inspect the first failed assertion. Do not
delete private-chain data, keys or event queues to troubleshoot isolated tests.
Pages 5-6 of the report group the testing guide and gas evaluation together:
test commands/results first, then profiling commands, the gas table and its interpretation.

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

The service refuses incomplete data. Historical validation evidence is kept in
docs/bitcoin-validation.json; rerun the command above when replacing the dataset.

## Start the private chain

Terminal 1:

    cd private-chain
    ./geth --datadir=./data init project2526genesis.json
    ./geth --datadir=./data --keystore=./keystore --networkid=202526 \
      --http --http.addr=127.0.0.1 --http.port=8545 --http.api=eth,net,web3 \
      --mine --miner.gasprice=100000000 \
      --miner.etherbase=d278d247a52c550508ea2b2c9321d816238fb523 \
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

The oracle has two phases. At each start it reconstructs the UTXO set **in
memory**, processing the first 131,000 blocks one at a time. It then serves
Ethereum balance-update requests using that index. Wait until the oracle prints
**ORACLE READY** before starting the demo; initial synchronization can take longer
than the demo's default five-minute timeout. There is no fixed sleep to configure.

No Bitcoin balance or UTXO cache is saved to disk. Restarting the oracle repeats
the replay. The SQLite event queue described below stores requests and signed
Ethereum transactions only, so requests made during synchronization can be
recovered. It is separate from the in-memory Bitcoin index.

Select an address with sufficient capacity from the validated data summary:

    ./.venv/bin/python python/simulate.py --btc-address 1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNa --principal 1

This concrete address has 4,000,000 satoshi in the validated project snapshot,
enough for the default 1 ETH request at the fixed exchange rate. If your input
differs, use an address from your own validated summary with sufficient capacity;
do not pass a literal placeholder such as `YOUR_VALIDATED_ADDRESS`.

BTC_ADDRESS can alternatively be set in the demo environment. The demo waits for
a fresh oracle event, checks actual liquidity and contributes enough capital.
It then runs two scenarios, each with a real YES vote and at least 12 voting blocks:

1. **Successful loan:** the requested principal, at 5% interest, is repaid in two
   installments and the contributor claims the accrued gain.
2. **Failed loan:** half that principal (rounded down, minimum 1 wei), at 10%, is
   left unpaid beyond its three-block term. A compensation request records default
   and pays only what the reserve can cover. A second request demonstrates that an
   empty reserve pays zero without erasing the remaining claim or counting failure twice.

With `--principal 1` on a fresh deployment, the contributor deposits 50 ETH.
The first loan generates 0.025 ETH in gain and 0.025 ETH in reserve. The second
loan disburses 0.5 ETH; compensation pays 0.025 ETH to the contributor's wallet.
The final pool position is **49.975 ETH total = 49.5 ETH disposable + 0.475 ETH
locked**. The remaining locked amount is an unpaid principal claim, not cash that
can be withdrawn. The reserve is empty, active loans are zero, failed loans are
one and global collateral returns from 45% to 50%. Existing positions, votes or
reserves can change these numbers when reusing a deployment.

All receipt statuses are checked. Compensation checks include payout, reserve,
principal claim, contributor/pool accounting and one-time failure adjustments.
Balances, collateral, current/due blocks and loan states are printed along the
way. Passing the deadline alone does not execute a transaction: default is recorded
by the subsequent request. With 10-second Clique blocks, allow several minutes for
both voting periods; `--timeout` applies separately to each asynchronous step.

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

## File guide

| File or directory | Purpose |
| --- | --- |
| contracts/FundingPool.sol | Contributions, votes, loan creation, interest and compensation accounting. |
| contracts/FundingPoolProxy.sol | Holds ETH and state while allowing the pool implementation to be upgraded. |
| contracts/LoanContract.sol | One loan's installments, expiry and repayment state. |
| contracts/BitcoinOracle.sol | Paid update requests and Bitcoin balances stored on Ethereum. |
| contracts/ContributorOrder.sol | Orders contributors for principal refunds. |
| contracts/test/ | V2 upgrade example, unsafe pool, attacker and native Solidity tests; not deployed by setup. |
| test/ | TypeScript tests, deployment helpers and gas profiling. |
| python/setup.py | Creates accounts, funds them and deploys the service on Geth. |
| python/simulate.py | Demonstrates repayment, default, partial compensation and an empty-reserve retry. |
| python/oracle/ | Bitcoin block parser, offline data checker and running oracle service. |
| python/voter/auto_voter.py | Always-YES contributor strategy required by the trace. |
| python/durable_events.py | Shared event scanning, retry and transaction handling for both services. |
| python/tests/ | Offline tests for Bitcoin data, service reliability and demo invariants. |
| private-chain/ | Course genesis, supplied account and local Geth installation/data. |
| docs/report.tex, docs/report.pdf | Source and final report for submission. |
| docs/report-it.tex, docs/report-it.pdf | Italian translation of the report, with the same structure, commands and measurements. |
| docs/guida-orale.tex, docs/guida-orale.pdf | Original Italian study guide: architecture, accounting, demo and oral-exam questions. |
| docs/default-demo-verification.json | New isolated Geth verification of both demo scenarios, with source hashes and final accounting. |
| docs/gas-measurements.json, docs/gas-table.tex | Measured gas costs and the generated report table. |
| docs/gas-table-it.tex | Italian gas table generated from the same measurements with --language it. |
| scripts/prepare_submission.py | Creates an allowlisted submission folder and ZIP without local deployment data. |
| scripts/tests/ | Independent safety tests for the submission builder (standard library only). |

setup.sh installs the development tools; python/setup.py deploys the application.
Neither test fixtures nor test contracts are alternative service implementations.

node_modules/, .venv/, artifacts/, cache/ and coverage/ are generated development
directories. They are not application source. Keep the local Bitcoin files, chain
data, .env files and service queues when continuing an existing deployment.
`npm run clean` clears Hardhat build output; subsequent tests/builds recreate it.

## Report and submission

To regenerate the report after profiling:

    python3 docs/render_gas_table.py
    cd docs
    latexmk -pdf -interaction=nonstopmode -halt-on-error report.tex

The separate Italian translation is docs/report-it.pdf; the English report is
not replaced. To regenerate its localized gas table and PDF from the project root:

    ./.venv/bin/python docs/render_gas_table.py --language it
    cd docs
    latexmk -pdf -interaction=nonstopmode -halt-on-error report-it.tex

Without --language, the gas-table generator keeps producing the original
English table. Both languages read the same docs/gas-measurements.json; Italian
number formatting uses decimal commas and thousands separators as appropriate.

The separate Italian oral-exam guide is a study aid, not part of the report's
page limit. It explains this implementation (not the colleague's project), with
plain-language explanations, worked examples, numbered excerpts loaded directly
from the real source files, and questions/model answers for a code-reading oral exam.
The LaTeX source includes excerpts by line range; recheck those ranges if code moves.
To regenerate it, run `latexmk -pdf -interaction=nonstopmode -halt-on-error guida-orale.tex`
from docs/. The current report has six pages: architecture/protocol, security,
the service user manual, an observed-run walk-through with final accounting,
and a two-page section combining testing and gas evaluation. The sixth page
was added at the author's request to preserve readability. The assignment
formally limits the report to five pages, so this longer version needs the
instructor's acceptance or must be shortened before submission. The separate
oral-exam study guide remains complete and unchanged.

The Geth demo recorded in docs/geth-demo.json verifies the 11 October 2026 sources
and Bitcoin data; its source hashes identify that specific run.
It used the course genesis, 15 successful receipts and 20 final state checks.
docs/bitcoin-validation.json records the corresponding full Bitcoin replay.
These files preserve historical evidence; they do not certify later code changes.
The new two-scenario integration is recorded separately in
docs/default-demo-verification.json: Geth 1.13.14 on an isolated course-genesis
chain, a real 131,000-block Bitcoin replay, 20 successful transaction receipts
and 16 final-state checks. It confirms repayment, default, partial compensation
and a zero-reserve retry for the selected source hashes. The existing local chain
and service environments were not modified by that verification.
Before submission, prepare the course ZIP with source, tests, configuration,
lockfile, scripts and the report.
Omit node_modules, .venv, .env, event databases and regenerable
Ethereum data. Make the exact Bitcoin snapshot available according to course rules.

### Prepare the submission folder and ZIP

From the project root, use Python 3.10+; no installed Node/Python dependencies,
running chain or generated service configurations are needed for packaging:

    python3 -m unittest discover -s scripts/tests -v
    python3 scripts/prepare_submission.py

This creates `submission/Decentralised-Lending-Service-683674-en/` and the
matching `.zip`. The ZIP contains exactly that one top-level folder: the
complete Hardhat project (Solidity, TypeScript tests/helpers, configuration,
package manifest and lockfile), Python application/tests, setup script,
`docs/report.pdf` in English and the original private-chain laboratory material.
The supplied laboratory keystore/password are required by the documented Geth
and setup commands; no generated service accounts or personal keys are included.

`docs/` initially contains only the selected PDF. The report provides the user
manual, test commands and gas analysis; no README, SUBMISSION.md, manifest,
packaging scripts or repository metadata are included in the ZIP. The README
and submission builder remain available in the repository. The builder prints
the ZIP checksum without creating a manifest. Files are selected explicitly, not
by copying the working tree or by assuming `.gitignore` protects secrets.
Source symlinks and an unexpected laboratory account are rejected.

The personal oral-exam guide, other report language, historical run evidence,
assignment PDF, dependencies, .env files, SQLite queues, chain state, Bitcoin
data, Geth binary and build/LaTeX intermediates are deliberately omitted.
LaTeX sources, logo, gas tables and their renderer stay in the repository, not
in the ZIP. Gas tests create `docs/gas-measurements.json` when executed, so an
initial measurement file is not needed to run them. The repository README
documents study material and report generation separately from the delivery.
The full real demonstration still needs the external Bitcoin dataset described
above; packaging does not make that input optional.

English is the default. To select Italian, use `--report-language it`; the
selected PDF is always named `docs/report.pdf` inside the ZIP. Existing output folders
and ZIPs are never overwritten. After further changes, create another snapshot:

    python3 scripts/prepare_submission.py --output-dir submission/revised

Before uploading, extract the exact ZIP into a new directory, run `./setup.sh`,
then the type check, contract tests and Python tests documented in the report. Do not
deploy or run the real demo just to execute the isolated tests. Creating the
ZIP does not itself run tests, change the report or waive its five-page limit.
