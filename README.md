# Decentralised Lending Service

A blockchain-based peer-to-peer (P2P) lending protocol built on Ethereum that enables direct borrowing and lending with Bitcoin collateral verification through an oracle mechanism.

## 📋 Project Overview

This project implements a decentralized lending platform where:
- **Contributors** deposit ETH into a funding pool and earn interest from successful loans
- **Borrowers** can request loans backed by Bitcoin collateral
- **Automated voting** determines loan approval based on configurable risk parameters
- **Bitcoin Oracle** verifies borrower Bitcoin balances to ensure collateral availability
- **Smart contract upgradability** via UUPS proxy pattern for future improvements

### Key Innovation: Bitcoin Collateral Integration

The system uniquely bridges Ethereum and Bitcoin by using an on-chain Bitcoin oracle that:
- Listens for collateral verification requests from borrowers
- Queries Bitcoin blockchain data via Python scripts
- Updates verified Bitcoin balances on-chain
- Enables risk assessment based on real Bitcoin holdings

## 🏗️ Architecture

```mermaid
flowchart TD
    %% Actors
    Borrower([Borrower])
    Contributor([Contributor])

    %% Blockchains & On-Chain
    subgraph Ethereum Blockchain
        direction TB
        FundingPool[FundingPool.sol]
        LoanContract[LoanContract.sol]
        BitcoinOracle[BitcoinOracle.sol]
    end

    subgraph Bitcoin Blockchain
        BTC[(Bitcoin UTXOs)]
    end

    %% Off-Chain Services
    subgraph Off-Chain Services (Python)
        OracleService[Oracle Service]
        AutoVoter[Auto-Voter]
    end

    %% Interactions
    Contributor -- "Deposits/Withdraws ETH" --> FundingPool
    Borrower -- "Submits Loan Proposal" --> FundingPool
    Borrower -- "Pays Fee & Requests Update" --> BitcoinOracle
    
    FundingPool -- "Creates & Funds" --> LoanContract
    Borrower -- "Repays Principal + Interest" --> LoanContract
    LoanContract -- "Returns Funds & Forwards Repayment" --> FundingPool

    BitcoinOracle -- "Emits UpdateRequested Event" --> OracleService
    OracleService -- "Reads Address Balance" --> BTC
    OracleService -- "Submits Verified Balance" --> BitcoinOracle
    
    FundingPool -- "Reads Validated Balance" --> BitcoinOracle
    FundingPool -- "Emits LoanProposed Event" --> AutoVoter
    AutoVoter -- "Automatically Votes 'Yes'" --> FundingPool
```

### Smart Contracts

#### 1. **FundingPool.sol** (UUPS Upgradeable)
The central hub managing loans, contributions, and voting.

**Core Functions:**
- `contribute()` - Contributors deposit ETH to earn interest
- `createLoanProposal()` - Borrowers submit loan requests with terms
- `voteOnProposal()` - Contributors vote on loan approval
- `executeApprovedLoan()` - Creates funded LoanContract after approval
- `handleRepayment()` - Receives repayments and distributes gains/collateral
- `requestCompensation()` - Contributors claim compensation from failed loans

**Key Features:**
- **Voting Mechanism:** Voting period = 12 blocks; approval requires Yes votes > 50% of total pool unlocked funds (non-voters count as implicit rejects)
- **Interest Distribution:** Loan interest split between gains and collateral pool (default 50/50)
- **Compensation Pool:** Accumulates collateral from loan failures. Targeted compensation requests forfeit future loan repayments.
- **Collateral Requirement:** Borrowers must have Bitcoin balance ≥ principal / 30 BTC
- **Termination Logic:** Pool can be terminated after all loans resolved; funds returned to contributors

#### 2. **LoanContract.sol**
Individual loan contract deployed for each approved proposal.

**Loan Lifecycle:**
```
Created → Funded → Repaid/Defaulted
```

**Core Functions:**
- `fundLoan()` - Pool sends ETH to borrower (only pool can call)
- `repay()` - Borrower repays principal + interest (supports partial repayments)
- `markDefaulted()` - Marks loan as defaulted if overdue (only pool can call)

**Interest Calculation:**
```
Total Interest = Principal × (interestRate / 100)
Example: 1 ETH at 5% = 0.05 ETH interest
```

**Collateral Distribution on Repayment:**
- Interest paid splits into:
  - **Collateral** = interest × collateral_percentage (e.g., 50%)
  - **Gain** = interest × (100 - collateral_percentage)
- Excess payments beyond principal + interest go to collateral pool

#### 3. **BitcoinOracle.sol** (Ownable)
Bridges Bitcoin and Ethereum by tracking Bitcoin address balances.

**Workflow:**
1. Borrower calls `requestUpdate(btcAddress)` with fee payment
2. Emits `UpdateRequested` event listened to by Python oracle service
3. Python service queries Bitcoin blockchain
4. Oracle owner calls `update(btcAddress, balanceInSatoshi)` with verified balance
5. FundingPool reads balance via `getBalance(btcAddress)`

**Fee Model:**
- Configurable minimum fee (default: 0.001 ETH)
- Paid by borrower requesting collateral verification

## 🔧 Technology Stack

### Smart Contracts
- **Language:** Solidity 0.8.24
- **Framework:** Hardhat
- **Dependencies:**
  - OpenZeppelin Contracts (upgradeable patterns)
  - OpenZeppelin Contracts-Upgradeable 5.6.1

### Local Blockchain
- **Network:** Geth (Go Ethereum)
- **Chain ID:** 202526
- **Block Time:** ~10 seconds
- **Configuration:** See `private-chain/` directory

### Python Integration
- **Oracle Service** (`python/oracle/oracle_service.py`):
  - Listens for `UpdateRequested` events
  - Queries Bitcoin blockchain
  - Parses UTXO data to calculate addresses
  - Calls oracle `update()` function

- **Auto-Voter** (`python/voter/auto_voter.py`):
  - Monitors `LoanProposed` events
  - Automatically and unconditionally votes YES on all proposals (as per Trace specifications)

### Development Tools
- Node.js & npm
- Ethers.js v6.13.4
- Chai for testing
- Python 3 with Web3.py

## 🚀 Quick Start

### 1. Installation

```bash
# Install Node dependencies
npm install

# Install Python dependencies
pip install web3 python-dotenv
```

### 2. Start Private Blockchain

```bash
# Terminal 1: Start Geth node
cd private-chain
./geth --datadir=./data --http --http.addr=127.0.0.1 --http.port=8545 \
  --networkid=202526 --authrpc.port=8551 --http.api=eth,net,web3 &
```

### 3. Deploy Contracts

```bash
# Terminal 2: Deploy to private network
python python/setup.py
```

This will:
- Generate random accounts for deployer, contributor, and borrower
- Fund them from pre-funded Geth account
- Deploy BitcoinOracle and FundingPool contracts
- Generate `.env` file with contract addresses

### 4. Run Python Services (Optional)

```bash
# Terminal 3: Run Bitcoin Oracle
python python/oracle/oracle_service.py

# Terminal 4: Run Auto-Voter
python python/voter/auto_voter.py
```

### 5. Simulate Lending Flow

```bash
# Terminal 5: Run simulation
python python/simulate.py
```

## 📊 Lending Flow Example

### Complete Loan Lifecycle

```
1. CONTRIBUTION PHASE
   Contributor calls: pool.contribute(5 ETH)
   → Contributor balance: 5 ETH
   → Available for loans: 5 ETH

2. LOAN PROPOSAL PHASE
   Borrower calls: pool.createLoanProposal(
     borrower=0x123...,
     btcAddress="1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNa",
     principal=1 ETH,
     interestRate=5 (5%),
     duration=3600 blocks,
     votingPeriod=12 blocks
   )
   → Proposal created with ID=1
   → Voting window: current block → +12 blocks

3. COLLATERAL VERIFICATION PHASE
   Borrower calls: oracle.requestUpdate(btcAddress)
   with fee (0.001 ETH)
   → Emits UpdateRequested event
   → Python oracle service detects event
   → Queries Bitcoin blockchain for address balance
   → Oracle calls: oracle.update(btcAddress, satoshis)

4. COLLATERAL VALIDATION
   Pool verifies: btcBalance ≥ (principal / 30)
   Example: 1 ETH requires ≥ 0.0333 BTC ≈ 3.3M sats

5. VOTING PHASE (12 blocks)
   Contributor votes: pool.voteOnProposal(proposalId=1, support=true)
   → Can vote multiple times with different addresses
   → Voting weight = unlocked contribution balance
   → Result: Yes votes must exceed 50% of the total pool's unlocked funds

6. LOAN EXECUTION PHASE
   Borrower calls: pool.executeApprovedLoan(proposalId=1)
   → Creates new LoanContract for this proposal
   → FundingPool.fundLoan() sends 1 ETH to LoanContract
   → LoanContract.fundLoan() transfers 1 ETH to Borrower
   → Loan status: Funded

7. REPAYMENT PHASE
   Borrower calls: loanContract.repay()
   Sends: 1.05 ETH (principal + interest)
   
   Distribution:
   - Principal: 1.00 ETH (returned to pool)
   - Interest: 0.05 ETH
     - Collateral portion: 0.025 ETH (50%) → compensation pool
     - Gain portion: 0.025 ETH (50%) → distributed to contributors
   
   Loan status: Repaid
   Contributor gains: 0.025 ETH + share of interest pool

8. COMPENSATION DISTRIBUTION
   If loan defaults:
   → Compensation pool funds lost contributors
   → Failed loan count increases
   → Collateral from failed loans covers losses
```

## 🧪 Testing

### Run All Tests

```bash
npm test
```

### Test Categories

1. **fundingPool.test.js** - End-to-end integration testing
   - Contribution flow
   - Loan proposal & voting
   - Execution and repayment
   
2. **loancontract.unit.test.js** - LoanContract unit tests
   - Funding mechanism
   - Interest calculations
   - Partial repayments
   
3. **reentrancy.test.js** - Security tests
   - Reentrancy attack scenarios
   - Checks if vulnerabilities in ReentrancyVulnerableLoan are properly exploited
   
4. **security_edge_cases.test.js** - Edge case coverage
   - Boundary conditions
   - Invalid states
   - Authorization checks
   
5. **gas_profiling.test.js** - Gas efficiency analysis
   - Optimizes for costly operations
   
6. **gas_report.test.js** - Detailed gas reporting
   - Function-level gas consumption

### Example Test Run

```bash
# Run specific test file
npx hardhat test test/fundingPool.test.js

# Run with gas reporting
REPORT_GAS=true npx hardhat test
```

## 🔐 Security Considerations

### Implemented Security Measures

1. **Reentrancy Protection**
   - Uses checks-effects-interactions pattern
   - Safe external calls via low-level `.call()`

2. **Authorization**
   - `onlyPool()` modifier restricts LoanContract state changes
   - `onlyOwner()` for oracle updates (BitcoinOracle)

3. **Input Validation**
   - Checks for zero addresses
   - Validates amounts > 0
   - Ensures valid state transitions

4. **Upgradeable Pattern**
   - UUPS proxy pattern prevents unauthorized upgrades
   - Initialization guard prevents multiple initializations

### Known Considerations

- **ReentrancyVulnerableLoan.sol**: Intentionally vulnerable version for testing
- **Oracle Trust**: Assumes oracle owner is trusted (would be decentralized in production)
- **Bitcoin Balance Oracle**: Requires Python service for off-chain data fetching

## 📁 Project Structure

```
├── contracts/                      # Smart contracts
│   ├── BitcoinOracle.sol          # Bitcoin balance tracking
│   ├── FundingPool.sol            # Core lending protocol (upgradeable)
│   ├── LoanContract.sol           # Individual loan contracts
│   ├── ReentrancyVulnerableLoan.sol # Vulnerable version (for testing)
│   └── ReentrancyAttacker.sol     # Attack contract (for testing)
│
├── docs/                           # Documentation
│   └── report.tex                 # LaTeX Project Report
│
├── test/                          # Test suite
│   ├── fundingPool.test.js        # Integration tests
│   ├── loancontract.unit.test.js  # LoanContract tests
│   ├── reentrancy.test.js         # Security tests
│   ├── security_edge_cases.test.js # Edge case tests
│   ├── gas_profiling.test.js      # Gas analysis
│   ├── gas_report.test.js         # Gas reporting
│   └── advanced_behaviors.test.js # Partial repayment and compensation tests
│
├── python/                        # Off-chain services
│   ├── oracle/
│   │   ├── oracle_service.py      # Bitcoin oracle listener
│   │   └── btc_utils.py           # Bitcoin blockchain utilities
│   └── voter/
│       └── auto_voter.py          # Automated proposal voting bot
│
├── private-chain/                 # Local Geth blockchain
│   ├── geth                       # Geth executable
│   ├── data/                      # Blockchain data
│   ├── keystore/                  # Account keys
│   └── genesis.json               # Chain configuration
│
├── artifacts/                     # Compiled contracts (generated)
├── cache/                         # Compiler cache (generated)
├── hardhat.config.js              # Hardhat configuration
├── package.json                   # Node dependencies
└── README.md                      # This file
```

## 🔄 Key Workflow Diagrams

### Voting Mechanism
```
┌─────────────┐
│   Propose   │ → [Voting Period: 12 blocks]
└─────────────┘
      ↓
┌─────────────────────────────────┐
│ Contributors Vote (Weighted)    │
│ - Yes votes > 50% of total pool │
│ - Non-voters = implicit reject  │
└─────────────────────────────────┘
      ↓
┌─────────────────────────────────┐
│ Execution (If Approved)         │
│ - Create LoanContract           │
│ - Fund borrower with principal  │
└─────────────────────────────────┘
```

### Interest Distribution
```
Loan Repayment (1.05 ETH)
      ↓
Principal (1.00 ETH) → Pool Reserve
      ↓
Interest (0.05 ETH) → Split 50/50
  ├─ Collateral (0.025 ETH) → Compensation Pool
  └─ Gain (0.025 ETH) → Contributor Distribution
```

## 🚨 Environment Variables

Create a `.env` file after deployment:

```env
ETH_RPC_URL=http://127.0.0.1:8545
POOL_ADDRESS=0x...
ORACLE_ADDRESS=0x...
VOTER_PRIVATE_KEY=0x...
```

## 📝 Configuration

### FundingPool Constants
- `BTC_TO_ETH_RATE` = 30 (1 ETH = 30 BTC for collateral calculation)
- `SATS_PER_BTC` = 100,000,000
- `MIN_DEPOSIT_WEI` = 100,000 wei
- `PROPOSAL_VOTING_PERIOD_BLOCKS` = 12 blocks
- `MIN_COLLATERAL_PERCENTAGE` = 1%
- `MAX_COLLATERAL_PERCENTAGE` = 100%

### Auto-Voter Strategy
- The script uses a trace-compliant strategy that **always votes YES** on any new loan proposal, regardless of interest or duration parameters.

## 🎓 Academic Context

This project is developed as part of a **Peer-to-Peer Systems and Blockchain** university course, implementing:
- Smart contract design patterns (UUPS proxy, authorization, state machines)
- Decentralized voting mechanisms
- Cross-chain oracle integration
- Security best practices for financial protocols

## 📄 License

MIT

## 🤝 Contributing

This is an educational project. Modifications and improvements are welcome for learning purposes.

## 📞 Support

For issues or questions about the project:
1. Check the test files for usage examples
2. Review security considerations section
3. Consult Solidity and Hardhat documentation

---

**Last Updated:** 2026-08-15
**Solidity Version:** 0.8.24
**Hardhat Version:** 2.29.0
