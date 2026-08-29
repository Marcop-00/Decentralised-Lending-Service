// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import "@openzeppelin/contracts-upgradeable/proxy/utils/Initializable.sol";
import "@openzeppelin/contracts-upgradeable/proxy/utils/UUPSUpgradeable.sol";
import "@openzeppelin/contracts-upgradeable/access/OwnableUpgradeable.sol";
import "./LoanContract.sol";
import "./BitcoinOracle.sol";

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
    error ProposalRejected();
    error InvalidAddress();
    error InvalidBitcoinAddress();
    error ProposalRejectedByLiquidity();
    error InvalidVotingPeriod();
    error InvalidInterestRate();
    error CompensationPoolEmpty();
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

    struct LoanProposal {
        address borrower;
        string borrowerBtcAddress;
        uint256 principal;
        uint256 interestRate;
        uint256 durationBlocks;
        uint256 votingDeadlineBlock;
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
    function withdraw(uint256 amount) external {
        if (amount == 0) revert AmountMustBeGreaterThanZero();

        uint256 unlocked = unlockedBalanceOf(msg.sender);
        if (amount > unlocked) revert InsufficientUnlockedBalance();

        totalContributed[msg.sender] -= amount;
        totalUnlockedFunds -= amount;

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

    /// @dev Refunds the locked base principal back to contributors proportionally when a loan is repaid.
    /// Sorts contributors by initial locked amount descending to optimize distribution logic.
    function _refundLockedContributors(uint256 proposalId, uint256 baseAmount) internal {
        if (baseAmount == 0) return;

        uint256 remaining = baseAmount;
        address[] memory loanContrs = loanContributors[proposalId];
        
        address[] memory order = new address[](loanContrs.length);
        for (uint256 i = 0; i < loanContrs.length; i++) {
            order[i] = loanContrs[i];
        }

        for (uint256 i = 0; i < order.length; i++) {
            uint256 maxIndex = i;
            for (uint256 j = i + 1; j < order.length; j++) {
                uint256 lockedJ = initialLoanContributions[proposalId][order[j]];
                uint256 lockedMax = initialLoanContributions[proposalId][order[maxIndex]];
                if (lockedJ > lockedMax) {
                    maxIndex = j;
                } else if (lockedJ == lockedMax && uint160(order[j]) > uint160(order[maxIndex])) {
                    maxIndex = j;
                }
            }
            if (maxIndex != i) {
                address temp = order[i];
                order[i] = order[maxIndex];
                order[maxIndex] = temp;
            }
        }

        for (uint256 i = 0; i < order.length && remaining > 0; i++) {
            address contributor = order[i];
            uint256 lockedForLoan = loanContributions[proposalId][contributor];
            if (lockedForLoan == 0) continue;

            uint256 refund = remaining < lockedForLoan ? remaining : lockedForLoan;
            
            loanContributions[proposalId][contributor] -= refund;
            lockedContributions[contributor] -= refund;
            
            totalUnlockedFunds += refund;
            remaining -= refund;
        }

        if (remaining > 0) {
            compensationPoolBalance += remaining;
        }
    }

    /// @dev Locks funds across all contributors proportionally based on their current unlocked balances.
    /// @param requiredAmount The target principal amount to lock.
    /// @param proposalId The ID of the loan proposal.
    /// @return totalLocked The total amount locked (may be slightly less than required due to integer division).
    /// @return actualDisbursement The exact amount that should be sent to the borrower.
    function _lockContributorsProportionally(uint256 requiredAmount, uint256 proposalId) internal returns (uint256 totalLocked, uint256 actualDisbursement) {
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

            uint256 lockAmount = (disposable * requiredAmount) / totalDisposable;
            if (lockAmount == 0) continue;

            lockedContributions[contributor] += lockAmount;
            totalUnlockedFunds -= lockAmount;
            
            loanContributions[proposalId][contributor] = lockAmount;
            initialLoanContributions[proposalId][contributor] = lockAmount;
            loanContributors[proposalId].push(contributor);
            
            totalLocked += lockAmount;
        }

        uint256 discrepancy = requiredAmount - totalLocked;
        actualDisbursement = requiredAmount - discrepancy;
        return (totalLocked, actualDisbursement);
    }

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
            
            uint256 share = (gainAmount * initialLocked) / totalInitialLocked;
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

    function _adjustCollateralPercentage(bool loanSucceeded) internal {
        if (loanSucceeded) {
            collateralPercentage = collateralPercentage > 5 ? collateralPercentage - 5 : MIN_COLLATERAL_PERCENTAGE;
        } else {
            collateralPercentage = collateralPercentage < 95 ? collateralPercentage + 5 : MAX_COLLATERAL_PERCENTAGE;
        }
    }

    function claimInterestGain() external {
        uint256 amount = pendingInterestGain[msg.sender];
        if (amount == 0) revert InvalidState();

        pendingInterestGain[msg.sender] = 0;

        (bool sent, ) = payable(msg.sender).call{value: amount}("");
        if (!sent) revert TransferFailed();
    }

    function requestCompensation(address loanAddress) external {
        if (!authorizedLoanContracts[loanAddress]) revert InvalidAddress();
        
        uint256 proposalId = loanToProposalId[loanAddress];
        LoanContract loan = LoanContract(loanAddress);
        if (loan.status() == LoanContract.LoanStatus.Repaid) revert InvalidState();
        if (block.number <= loan.dueBlock()) revert InvalidState();

        // Mark the loan as defaulted before compensating. A defaulted loan can
        // still accept late repayments, but it can never become successful.
        if (loan.status() == LoanContract.LoanStatus.Funded) {
            loan.markDefaulted();
        }

        if (!isLoanFailed[proposalId]) {
            isLoanFailed[proposalId] = true;
            failedLoanCount += 1;
            _adjustCollateralPercentage(false);
        }
        
        uint256 owedAmount = loanContributions[proposalId][msg.sender];
        if (owedAmount == 0) revert AmountMustBeGreaterThanZero();
        
        uint256 actualCompensation = owedAmount;
        if (actualCompensation > compensationPoolBalance) {
            actualCompensation = compensationPoolBalance;
        }

        if (actualCompensation == 0) revert CompensationPoolEmpty();

        loanContributions[proposalId][msg.sender] -= actualCompensation;
        lockedContributions[msg.sender] -= actualCompensation;
        // Compensation is paid out of the compensation pool, not converted
        // into a second withdrawable claim against the funding pool.
        totalContributed[msg.sender] -= actualCompensation;
        
        compensationPoolBalance -= actualCompensation;

        (bool sent, ) = payable(msg.sender).call{value: actualCompensation}("");
        if (!sent) revert TransferFailed();

        emit CompensationRequested(msg.sender, actualCompensation);
    }

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
            emit CompensationPoolFunded(collateralAmount, collateralPercentage);
        }

        LoanContract loan = LoanContract(msg.sender);
        if (loan.status() == LoanContract.LoanStatus.Repaid && !loanResolved[msg.sender]) {
            loanResolved[msg.sender] = true;
            activeLoanCount -= 1;
            _adjustCollateralPercentage(true);
        }
    }

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
        }
    }

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

    function voteOnProposal(uint256 proposalId, bool support) external notTerminated {
        LoanProposal storage proposal = proposals[proposalId];
        if (proposal.borrower == address(0)) revert InvalidProposal();
        if (block.number >= proposal.votingDeadlineBlock) revert VotingClosed();
        if (hasVoted[proposalId][msg.sender]) revert AlreadyVoted();

        uint256 weight = unlockedBalanceOf(msg.sender);
        if (weight == 0) revert NoVotingPower();

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

        (uint256 lockedAmount, uint256 disbursedAmount) = _lockContributorsProportionally(proposal.principal, proposalId);
        if (lockedAmount == 0) {
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
