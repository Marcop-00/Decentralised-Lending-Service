Decentralised Lending Service — Project

Overview
--------
This repository implements a simple decentralised lending service for the course lab. Core contracts:
- FundingPool.sol — pool of contributed ETH. Owner can create loan proposals, contributors vote, and owner executes the approved loan which deploys a LoanContract.
- LoanContract.sol — per-loan contract to fund, accept repayment, and mark defaulted loans.
- BitcoinOracle.sol — on-chain oracle where off-chain updater can post BTC balances (in satoshis) for a BTC address; FundingPool queries this to estimate borrower liquidity.

What I inspected and actions taken
---------------------------------
- Reviewed all contracts, scripts, and the project genesis file.
- Removed two committed secret files (a keystore and a password file) from the current branch and added REMEDIATION.md with instructions to rotate keys and purge history. DO NOT assume those keys are safe.
- Added an integration-style test (test/fundingPool.test.js) and a unit test for LoanContract. Tests may require dependency updates / Node >=22 to run with the latest Hardhat toolbox — see the "Run tests" section below.

High-level recommended project tasks (mapped to the professor PDF)
-----------------------------------------------------------------
The professor PDF specifies the required deliverables for the lab (deployment, tests, and demonstration). Based on the repository contents and the PDF, the following tasks complete the project:

1) Security remediation (done locally, action required by you):
   - Rotate any accounts revealed by the committed keystore/password files.
   - Purge secrets from git history (git-filter-repo or BFG) and force-push (coordinate with team).
   - Move any sensitive keys to a secure vault or use environment variables in CI.

2) Test coverage (increase & verify):
   - Run the included tests (unit + integration). Expand tests to cover edge cases: voting ties, insufficient liquidity, locking/unlocking funds, withdraw edge cases, loan default handling.
   - Tests provided use the Hardhat/Ethers test environment.

3) Deployment & scripts:
   - Provide a deployment script to deploy BitcoinOracle and FundingPool.
   - Provide an off-chain oracle updater script that pays the oracle fee and sets BTC balances.
   - Add a demo script showing an end-to-end flow (contribute -> propose -> vote -> execute -> repay).

4) Documentation:
   - Add README (this file) with run instructions, known environment issues, and security notes.
   - Provide example .env (already present as .env.example) and instructions to use local genesis.

5) Tooling and environment:
   - Prefer Node 22+ if you want to use the latest Hardhat toolbox and plugins.
   - If you cannot upgrade Node on your machine, run tests in a container or revert to older plugin versions compatible with your Node version.

How to run (recommended)
------------------------
1. Install Node (recommended): use Node 22.x (nvm install 22 && nvm use 22).
2. Install dependencies: npm ci
3. Compile contracts: npm run compile
4. Run tests: npm test

If you prefer not to upgrade Node here, follow the original package.json devDependency versions and run tests locally in an environment you control.

Files added
-----------
- REMEDIATION.md  — instructions for rotating keys and purging history (sensitive file remediation).
- test/fundingPool.test.js — an end-to-end integration-style test (added earlier).
- test/loancontract.unit.test.js — a small unit test for LoanContract.
- scripts/deploy.js — deployment script for BitcoinOracle -> FundingPool.
- scripts/updateOracle.js — sample off-chain oracle updater script.

Notes about tests and environment
---------------------------------
- In this environment I compiled the contracts successfully, but running the full test suite hit a toolchain mismatch (Hardhat/toolbox vs Node version). To get deterministic passing test runs, use Node 22+ or run the tests locally after installing the appropriate plugins.

Next steps you can ask me to do (I can continue autonomously):
- Expand tests to full coverage and make them pass in-ci by either upgrading Node in this environment or adapting dependencies to current Node.
- Implement deployment and demo scripts that run against a local hardhat node and create an automated demo sequence.
- Add GitHub Actions CI that runs tests and checks for secrets in commits.

Contact
-------
If you want, I can now:
- Run the remaining test and fix issues here (requires Node 22 in this environment), or
- Revert dependency upgrades and try to make tests run under Node 21, or
- Continue by adding more tests, deployment and demo scripts and CI config without changing the runtime Node here.

(End of README)
