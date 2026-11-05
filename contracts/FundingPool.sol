// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import "@openzeppelin/contracts-upgradeable/proxy/utils/Initializable.sol";
import "@openzeppelin/contracts-upgradeable/proxy/utils/UUPSUpgradeable.sol";
import "@openzeppelin/contracts-upgradeable/access/OwnableUpgradeable.sol";
import {Math} from "@openzeppelin/contracts/utils/math/Math.sol";
import "./LoanContract.sol";
import "./BitcoinOracle.sol";
import "./ContributorOrder.sol";

/// @title FundingPool
/// @notice Manages lending pool contributions, loan proposals, and voting mechanics.
/// @dev Implements UUPS proxy pattern for upgradeability.
contract FundingPool is Initializable, UUPSUpgradeable, OwnableUpgradeable {
    error AmountMustBeGreaterThanZero();
    error InsufficientUnlockedBalance();
    error InsufficientPoolLiquidity();
    error Unauthorized();
    error TransferFailed();
    error InvalidProposal();
    error InvalidState();
    error AlreadyVoted();
    error VotingClosed();
    error VotingStillActive();
    error NoVotingPower();
    error InvalidAddress();
    error InvalidBitcoinAddress();
    error InvalidVotingPeriod();
    error InvalidInterestRate();
    error ContractTerminated();
    error ActiveLoansExist();
    error DepositTooLow();

    event ContributionAdded(address indexed contributor, uint256 amount);
    event ContributionWithdrawn(address indexed contributor, uint256 amount);
    event FundsLocked(address indexed contributor, uint256 amount);
    event FundsUnlocked(address indexed contributor, uint256 amount);
    event CompensationPoolFunded(uint256 amount, uint256 collateralPercentage);
    event CompensationRequested(address indexed contributor, uint256 amount);
    event LoanProposed(
        uint256 indexed proposalId,
        address indexed borrower,
        string borrowerBtcAddress,
        uint256 principal,
        uint256 interestRate,
        uint256 durationBlocks,
        uint256 votingDeadlineBlock
    );
    event VoteCast(uint256 indexed proposalId, address indexed voter, bool support, uint256 weight);
    event LoanApproved(uint256 indexed proposalId, address indexed loanContract);
    event LoanRejected(uint256 indexed proposalId, string reason);
    event LoanDefaulted(uint256 indexed proposalId, address indexed loanContract);
    event InterestClaimed(address indexed contributor, uint256 amount);
    event Terminated();

    struct LoanProposal {
        address borrower;
        string borrowerBtcAddress;
        uint256 principal;
        uint256 interestRate;
        uint256 durationBlocks;
        uint256 votingDeadlineBlock; // ABI-compatible name: earliest resolution block, not a vote expiry.
        uint256 yesVotes;
        uint256 noVotes;
        bool executed;
        address loanContract;
    }

    mapping(address => uint256) public totalContributed;
    mapping(address => uint256) public lockedContributions;
    mapping(address => uint256) public pendingInterestGain;
    mapping(uint256 => LoanProposal) public proposals;
    mapping(uint256 => mapping(address => bool)) public hasVoted;
    mapping(uint256 => mapping(address => bool)) public voteSupport;
    mapping(address => bool) public authorizedLoanContracts;
    mapping(address => uint256) public loanToProposalId;
    mapping(address => bool) public isContributor;

    // --- Per-Loan Tracking (by proposalId) ---
    mapping(uint256 => address[]) public loanContributors;
    mapping(uint256 => mapping(address => uint256)) public loanContributions;
    mapping(uint256 => mapping(address => uint256)) public initialLoanContributions;
    mapping(uint256 => bool) public isLoanFailed;
    mapping(address => bool) public loanResolved;
    // -----------------------------------------

    address[] public contributors;

    uint256 public proposalCount;
    uint256 public totalUnlockedFunds;
    uint256 public compensationPoolBalance;
    uint256 public collateralPercentage;
    uint256 public failedLoanCount;
    uint256 public activeLoanCount;
    bool public terminated;
    BitcoinOracle public bitcoinOracle;

    // Appended storage: existing proxy slots and loan records retain their layout.
    mapping(uint256 => bool) private loanOrderPrepared;

    uint256 public constant BTC_TO_ETH_RATE = 30;
    uint256 public constant SATS_PER_BTC = 100_000_000;
    uint256 public constant MIN_DEPOSIT_WEI = 100_000;
    uint256 public constant PROPOSAL_VOTING_PERIOD_BLOCKS = 12;
    uint256 public constant MIN_COLLATERAL_PERCENTAGE = 1;
    uint256 public constant MAX_COLLATERAL_PERCENTAGE = 100;

    modifier notTerminated() {
        if (terminated) revert ContractTerminated();
        _;
    }

    constructor() {
        _disableInitializers();
    }

    function initialize(address oracleAddress) public initializer {
        if (oracleAddress == address(0)) revert InvalidAddress();

        __Ownable_init(msg.sender);
        bitcoinOracle = BitcoinOracle(oracleAddress);
        terminated = false;
        collateralPercentage = 50;
    }

    function _authorizeUpgrade(address newImplementation) internal override onlyOwner {}

    receive() external payable {
        if (!authorizedLoanContracts[msg.sender]) revert Unauthorized();
    }

    function terminate() external onlyOwner {
        if (activeLoanCount != 0) revert ActiveLoansExist();
        terminated = true;
        emit Terminated();
    }

    /// @notice Allows users to contribute ETH to the lending pool.
    /// @dev Updates the contributor's unlocked balance and total pool balance.
    function contribute() external payable notTerminated {
        if (msg.value <= MIN_DEPOSIT_WEI) revert DepositTooLow();

        totalContributed[msg.sender] += msg.value;
        totalUnlockedFunds += msg.value;
        _registerContributor(msg.sender);

        emit ContributionAdded(msg.sender, msg.value);
    }

    /// @notice Allows contributors to withdraw their unlocked funds.
    /// @param amount The amount of ETH to withdraw in wei.
    function withdraw(uint256 amount) external virtual {
        if (amount == 0) revert AmountMustBeGreaterThanZero();

        uint256 unlocked = unlockedBalanceOf(msg.sender);
        if (amount > unlocked) revert InsufficientUnlockedBalance();

        totalContributed[msg.sender] -= amount;
        totalUnlockedFunds -= amount;
        _unregisterEmptyContributor(msg.sender);

        (bool sent, ) = payable(msg.sender).call{value: amount}("");
        if (!sent) revert TransferFailed();

        emit ContributionWithdrawn(msg.sender, amount);
    }

    /// @notice Returns the amount of unlocked, freely available funds for a contributor.
    /// @param contributor The address of the contributor.
    /// @return Unlocked balance in wei.
    function unlockedBalanceOf(address contributor) public view returns (uint256) {
        return totalContributed[contributor] - lockedContributions[contributor];
    }

    /// @dev Registers a new contributor if they haven't deposited before.
    function _registerContributor(address contributor) internal {
        if (!isContributor[contributor]) {
            isContributor[contributor] = true;
            contributors.push(contributor);
        }
    }

    /// @dev Remove fully closed positions so deposit/withdraw churn does not
    /// permanently grow the list scanned at each proposal resolution.
    function _unregisterEmptyContributor(address contributor) internal {
        if (totalContributed[contributor] != 0 || !isContributor[contributor]) return;
        for (uint256 i = 0; i < contributors.length; i++) {
            if (contributors[i] == contributor) {
                contributors[i] = contributors[contributors.length - 1];
                contributors.pop();
                isContributor[contributor] = false;
                return;
            }
        }
    }

    /// @dev Refunds principal in descending order of initial locked amount;
    /// ties go to the numerically greater address, never to a changing balance.
    function _refundLockedContributors(uint256 proposalId, uint256 baseAmount) internal {
        if (baseAmount == 0) return;

        uint256 remaining = baseAmount;
        _prepareRefundOrder(proposalId);
        address[] memory order = loanContributors[proposalId];

        for (uint256 i = 0; i < order.length && remaining > 0; i++) {
            address contributor = order[i];
            uint256 lockedForLoan = loanContributions[proposalId][contributor];
            if (lockedForLoan == 0) continue;

            uint256 refund = remaining < lockedForLoan ? remaining : lockedForLoan;
            
            loanContributions[proposalId][contributor] -= refund;
            lockedContributions[contributor] -= refund;
            
            totalUnlockedFunds += refund;
            remaining -= refund;
            emit FundsUnlocked(contributor, refund);
        }

        if (remaining > 0) {
            compensationPoolBalance += remaining;
        }
    }

    /// @dev Store the immutable priority once; also prepares pre-upgrade loans
    /// lazily when their appended flag is still unset.
    function _prepareRefundOrder(uint256 proposalId) internal {
        if (loanOrderPrepared[proposalId]) return;
        address[] storage accounts = loanContributors[proposalId];
        ContributorOrder.Position[] memory positions = new ContributorOrder.Position[](accounts.length);
        for (uint256 i = 0; i < accounts.length; i++) {
            positions[i] = ContributorOrder.Position(accounts[i], initialLoanContributions[proposalId][accounts[i]]);
        }
        ContributorOrder.sort(positions);
        for (uint256 i = 0; i < accounts.length; i++) accounts[i] = positions[i].account;
        loanOrderPrepared[proposalId] = true;
    }

    /// @dev Locks funds across all contributors proportionally based on their current unlocked balances.
    /// @param requiredAmount The target principal amount to lock.
    /// @param proposalId The ID of the loan proposal.
    /// @return totalLocked The actual principal to disburse, after proportional rounding.
    function _lockContributorsProportionally(uint256 requiredAmount, uint256 proposalId) internal returns (uint256 totalLocked) {
        uint256 totalDisposable = 0;
        for (uint256 i = 0; i < contributors.length; i++) {
            totalDisposable += unlockedBalanceOf(contributors[i]);
        }

        if (totalDisposable == 0 || requiredAmount > totalDisposable) revert InsufficientPoolLiquidity();

        // Each position is the floor of its proportional share.  The trace
        // explicitly requires that finite-precision remainder is deducted
        // from the amount disbursed to the borrower, rather than assigned to
        // an arbitrary contributor.
        for (uint256 i = 0; i < contributors.length; i++) {
            address contributor = contributors[i];
            uint256 disposable = unlockedBalanceOf(contributor);
            if (disposable == 0) continue;

            uint256 lockAmount = Math.mulDiv(disposable, requiredAmount, totalDisposable);
            if (lockAmount == 0) continue;

            lockedContributions[contributor] += lockAmount;
            totalUnlockedFunds -= lockAmount;
            
            loanContributions[proposalId][contributor] = lockAmount;
            initialLoanContributions[proposalId][contributor] = lockAmount;
            loanContributors[proposalId].push(contributor);
            emit FundsLocked(contributor, lockAmount);
            
            totalLocked += lockAmount;
        }

        _prepareRefundOrder(proposalId);
    }

    /// @dev Distributes interest gains proportionally based on initial locked contributions.
    /// @param proposalId The ID of the loan proposal.
    /// @param gainAmount The amount of interest (gain) to distribute in wei.
    function _creditProportionalInterestGain(uint256 proposalId, uint256 gainAmount) internal {
        if (gainAmount == 0) return;
        
        address[] memory loanContrs = loanContributors[proposalId];
        if (loanContrs.length == 0) return;
        
        uint256 totalInitialLocked = 0;
        for (uint256 i = 0; i < loanContrs.length; i++) {
            totalInitialLocked += initialLoanContributions[proposalId][loanContrs[i]];
        }
        
        if (totalInitialLocked == 0) {
            compensationPoolBalance += gainAmount;
            return;
        }

        uint256 disbursed = 0;
        for (uint256 i = 0; i < loanContrs.length; i++) {
            address contributor = loanContrs[i];
            uint256 initialLocked = initialLoanContributions[proposalId][contributor];
            if (initialLocked == 0) continue;
            
            uint256 share = Math.mulDiv(gainAmount, initialLocked, totalInitialLocked);
            if (share > 0) {
                pendingInterestGain[contributor] += share;
                disbursed += share;
            }
        }
        
        uint256 leftover = gainAmount - disbursed;
        if (leftover > 0) {
            compensationPoolBalance += leftover;
        }
    }

    /// @dev Adjusts the global collateral percentage based on loan success or failure.
    /// Increases by 5% on failure, decreases by 5% on success, constrained between 1% and 100%.
    /// @param loanSucceeded True if the loan was fully repaid, false if it defaulted.
    function _adjustCollateralPercentage(bool loanSucceeded) internal {
        if (loanSucceeded) {
            collateralPercentage = collateralPercentage > 5 ? collateralPercentage - 5 : MIN_COLLATERAL_PERCENTAGE;
        } else {
            collateralPercentage = collateralPercentage < 95 ? collateralPercentage + 5 : MAX_COLLATERAL_PERCENTAGE;
        }
    }

    /// @notice Allows a contributor to claim their accrued interest gains.
    /// @dev Transfers the accumulated pending interest to the caller.
    function claimInterestGain() external {
        uint256 amount = pendingInterestGain[msg.sender];
        if (amount == 0) revert InvalidState();

        pendingInterestGain[msg.sender] = 0;

        (bool sent, ) = payable(msg.sender).call{value: amount}("");
        if (!sent) revert TransferFailed();
        emit InterestClaimed(msg.sender, amount);
    }

    /// @notice Requests compensation from the compensation pool for a failed loan.
    /// @dev The caller forfeits their remaining base repayment from the borrower.
    /// @param loanAddress The address of the failed LoanContract.
    function requestCompensation(address loanAddress) external {
        if (!authorizedLoanContracts[loanAddress]) revert InvalidAddress();
        
        uint256 proposalId = loanToProposalId[loanAddress];
        LoanContract loan = LoanContract(loanAddress);
        if (loan.status() == LoanContract.LoanStatus.Repaid) revert InvalidState();
        if (block.number <= loan.dueBlock()) revert InvalidState();

        uint256 owedAmount = loanContributions[proposalId][msg.sender];
        if (owedAmount == 0) revert AmountMustBeGreaterThanZero();

        // Mark the loan as defaulted before compensating. A defaulted loan can
        // still accept late repayments, but it can never become successful.
        if (loan.status() == LoanContract.LoanStatus.Funded) {
            loan.markDefaulted();
        }

        uint256 actualCompensation = owedAmount;
        if (actualCompensation > compensationPoolBalance) {
            actualCompensation = compensationPoolBalance;
        }

        // A valid claim still records the default when no compensation is
        // available. Keep the claim intact so it can be retried after a refill.
        if (actualCompensation == 0) {
            emit CompensationRequested(msg.sender, 0);
            return;
        }

        loanContributions[proposalId][msg.sender] -= actualCompensation;
        lockedContributions[msg.sender] -= actualCompensation;
        // Compensation is paid out of the compensation pool, not converted
        // into a second withdrawable claim against the funding pool.
        totalContributed[msg.sender] -= actualCompensation;
        _unregisterEmptyContributor(msg.sender);
        
        compensationPoolBalance -= actualCompensation;

        (bool sent, ) = payable(msg.sender).call{value: actualCompensation}("");
        if (!sent) revert TransferFailed();

        emit CompensationRequested(msg.sender, actualCompensation);
    }

    /// @notice Handles incoming repayments from a LoanContract.
    /// @dev Distributes base amount, credits interest, and funds the compensation pool.
    /// @param baseAmount The amount of principal repaid in this transaction.
    /// @param gainAmount The amount of interest distributed to contributors.
    /// @param collateralAmount The amount of interest sent to the compensation pool.
    function handleRepayment(
        uint256 baseAmount,
        uint256 gainAmount,
        uint256 collateralAmount
    ) external {
        if (!authorizedLoanContracts[msg.sender]) revert Unauthorized();
        
        uint256 proposalId = loanToProposalId[msg.sender];

        if (baseAmount > 0) {
            _refundLockedContributors(proposalId, baseAmount);
        }
        if (gainAmount > 0) {
            _creditProportionalInterestGain(proposalId, gainAmount);
        }
        if (collateralAmount > 0) {
            compensationPoolBalance += collateralAmount;
            emit CompensationPoolFunded(collateralAmount, LoanContract(msg.sender).collateralPercentage());
        }

        LoanContract loan = LoanContract(msg.sender);
        if (loan.status() == LoanContract.LoanStatus.Repaid && !loanResolved[msg.sender]) {
            loanResolved[msg.sender] = true;
            activeLoanCount -= 1;
            _adjustCollateralPercentage(true);
        }
    }

    /// @notice Marks a loan as defaulted in the pool's state.
    /// @dev Callable only by authorized LoanContracts when a default occurs.
    function handleLoanDefaulted() external {
        if (!authorizedLoanContracts[msg.sender]) revert Unauthorized();
        uint256 proposalId = loanToProposalId[msg.sender];
        if (!isLoanFailed[proposalId]) {
            isLoanFailed[proposalId] = true;
            failedLoanCount += 1;
            if (!loanResolved[msg.sender]) {
                loanResolved[msg.sender] = true;
                activeLoanCount -= 1;
            }
            _adjustCollateralPercentage(false);
            emit LoanDefaulted(proposalId, msg.sender);
        }
    }

    /// @notice Calculates the voting power of a contributor.
    /// @param contributor The address of the contributor.
    /// @return The current voting weight based on unlocked funds.
    function votingPowerOf(address contributor) external view returns (uint256) {
        return unlockedBalanceOf(contributor);
    }

    /// @notice Creates a new loan proposal to be voted on by contributors.
    /// @param borrower The Ethereum address of the borrower.
    /// @param borrowerBtcAddress The Bitcoin collateral address of the borrower.
    /// @param principal The requested loan amount in wei.
    /// @param interestRate The offered interest rate as a percentage (1-100).
    /// @param durationBlocks The duration of the loan in blocks.
    /// @param votingDurationBlocks The duration of the voting period in blocks.
    function createLoanProposal(
        address borrower,
        string calldata borrowerBtcAddress,
        uint256 principal,
        uint256 interestRate,
        uint256 durationBlocks,
        uint256 votingDurationBlocks
    ) external notTerminated returns (uint256 proposalId) {
        if (borrower == address(0)) revert InvalidAddress();
        if (borrower != msg.sender) revert Unauthorized();
        if (bytes(borrowerBtcAddress).length == 0) revert InvalidBitcoinAddress();
        if (principal == 0 || durationBlocks == 0) revert AmountMustBeGreaterThanZero();
        if (votingDurationBlocks != PROPOSAL_VOTING_PERIOD_BLOCKS) revert InvalidVotingPeriod();
        if (interestRate < 1 || interestRate > 100) revert InvalidInterestRate();

        proposalId = ++proposalCount;
        LoanProposal storage proposal = proposals[proposalId];
        proposal.borrower = borrower;
        proposal.borrowerBtcAddress = borrowerBtcAddress;
        proposal.principal = principal;
        proposal.interestRate = interestRate;
        proposal.durationBlocks = durationBlocks;
        proposal.votingDeadlineBlock = block.number + PROPOSAL_VOTING_PERIOD_BLOCKS;

        emit LoanProposed(
            proposalId,
            borrower,
            borrowerBtcAddress,
            principal,
            interestRate,
            durationBlocks,
            proposal.votingDeadlineBlock
        );
    }

    /// @notice Casts a vote on an active loan proposal.
    /// @param proposalId The ID of the loan proposal to vote on.
    /// @param support True to approve, false to reject.
    function voteOnProposal(uint256 proposalId, bool support) external notTerminated {
        LoanProposal storage proposal = proposals[proposalId];
        if (proposal.borrower == address(0)) revert InvalidProposal();
        if (proposal.executed) revert VotingClosed();
        if (hasVoted[proposalId][msg.sender]) revert AlreadyVoted();

        // Eligibility depends on the entire position, including locked value.
        // A zero-weight vote can become relevant before resolution.
        if (totalContributed[msg.sender] == 0) revert NoVotingPower();
        uint256 weight = unlockedBalanceOf(msg.sender);

        hasVoted[proposalId][msg.sender] = true;
        voteSupport[proposalId][msg.sender] = support;
        if (support) {
            proposal.yesVotes += weight;
        } else {
            proposal.noVotes += weight;
        }

        emit VoteCast(proposalId, msg.sender, support, weight);
    }

    /// @notice Executes an approved loan proposal, deploying a new LoanContract.
    /// @param proposalId The ID of the proposal to execute.
    /// @return loanAddress The address of the newly deployed LoanContract.
    function executeApprovedLoan(uint256 proposalId) external notTerminated returns (address loanAddress) {
        LoanProposal storage proposal = proposals[proposalId];
        if (proposal.borrower == address(0)) revert InvalidProposal();
        if (msg.sender != proposal.borrower) revert Unauthorized();
        if (block.number < proposal.votingDeadlineBlock) revert VotingStillActive();
        if (proposal.executed) revert InvalidState();

        // The trace defines vote weights using the contributors' current
        // disposable balances at resolution time. Non-voters are rejects.
        uint256 currentDisposable = totalUnlockedFunds;
        uint256 currentYesVotes = 0;
        for (uint256 i = 0; i < contributors.length; i++) {
            address contributor = contributors[i];
            if (hasVoted[proposalId][contributor] && voteSupport[proposalId][contributor]) {
                currentYesVotes += unlockedBalanceOf(contributor);
            }
        }
        proposal.yesVotes = currentYesVotes;
        proposal.noVotes = currentDisposable - currentYesVotes;

        if (currentYesVotes <= (currentDisposable / 2)) {
            proposal.executed = true;
            emit LoanRejected(proposalId, "Majority Reject");
            return address(0);
        }

        if (currentDisposable < proposal.principal) {
            proposal.executed = true;
            emit LoanRejected(proposalId, "Insufficient Liquidity");
            return address(0);
        }

        uint256 borrowerBalanceSats = bitcoinOracle.getBalance(proposal.borrowerBtcAddress);
        uint256 borrowerLiquidityInWei = (borrowerBalanceSats * BTC_TO_ETH_RATE * 1 ether) / SATS_PER_BTC;
        if (borrowerLiquidityInWei < proposal.principal) {
            proposal.executed = true;
            emit LoanRejected(proposalId, "Bitcoin Liquidity Check Failed");
            return address(0);
        }

        proposal.executed = true;

        uint256 disbursedAmount = _lockContributorsProportionally(proposal.principal, proposalId);
        if (disbursedAmount == 0) {
            emit LoanRejected(proposalId, "Failed to lock funds");
            return address(0);
        }

        LoanContract loan = new LoanContract(
            address(this),
            proposal.borrower,
            disbursedAmount,
            proposal.interestRate,
            proposal.durationBlocks,
            collateralPercentage
        );

        authorizedLoanContracts[address(loan)] = true;
        loanToProposalId[address(loan)] = proposalId;
        activeLoanCount += 1;
        loan.fundLoan{value: disbursedAmount}();
        proposal.loanContract = address(loan);
        loanAddress = address(loan);

        emit LoanApproved(proposalId, loanAddress);
    }
}
