// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import "@openzeppelin/contracts-upgradeable/proxy/utils/Initializable.sol";
import "@openzeppelin/contracts-upgradeable/proxy/utils/UUPSUpgradeable.sol";
import "@openzeppelin/contracts-upgradeable/access/OwnableUpgradeable.sol";
import "./LoanContract.sol";
import "./BitcoinOracle.sol";

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
    error CompensationPoolEmpty();
    error ContractTerminated();
    error ContractNotTerminated();

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
        uint256 interestBps,
        uint256 durationBlocks,
        uint256 votingDeadlineBlock
    );
    event VoteCast(uint256 indexed proposalId, address indexed voter, bool support, uint256 weight);
    event LoanApproved(uint256 indexed proposalId, address indexed loanContract);

    struct LoanProposal {
        address borrower;
        string borrowerBtcAddress;
        uint256 principal;
        uint256 interestBps;
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
    mapping(address => bool) public authorizedLoanContracts;
    mapping(address => bool) public isContributor;

    address[] public contributors;

    uint256 public proposalCount;
    uint256 public totalUnlockedFunds;
    uint256 public compensationPoolBalance;
    uint256 public collateralPercentage = 50;
    uint256 public failedLoanCount;
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

    function initialize(address oracleAddress) public initializer {
        if (oracleAddress == address(0)) revert InvalidAddress();

        __Ownable_init(msg.sender);
        bitcoinOracle = BitcoinOracle(oracleAddress);
        terminated = false;
    }

    function _authorizeUpgrade(address newImplementation) internal override onlyOwner {}

    receive() external payable {}

    function terminate() external onlyOwner {
        terminated = true;
    }

    function resume() external onlyOwner {
        terminated = false;
    }

    function contribute() external payable notTerminated {
        if (msg.value < MIN_DEPOSIT_WEI) revert AmountMustBeGreaterThanZero();

        totalContributed[msg.sender] += msg.value;
        totalUnlockedFunds += msg.value;
        _registerContributor(msg.sender);

        emit ContributionAdded(msg.sender, msg.value);
    }

    function withdraw(uint256 amount) external notTerminated {
        if (amount == 0) revert AmountMustBeGreaterThanZero();

        uint256 unlocked = unlockedBalanceOf(msg.sender);
        if (amount > unlocked) revert InsufficientUnlockedBalance();

        totalContributed[msg.sender] -= amount;
        totalUnlockedFunds -= amount;

        (bool sent, ) = payable(msg.sender).call{value: amount}("");
        if (!sent) revert TransferFailed();

        emit ContributionWithdrawn(msg.sender, amount);
    }

    function lockContributorFunds(address contributor, uint256 amount) external onlyOwner notTerminated {
        if (amount == 0) revert AmountMustBeGreaterThanZero();

        uint256 unlocked = unlockedBalanceOf(contributor);
        if (amount > unlocked) revert InsufficientUnlockedBalance();

        lockedContributions[contributor] += amount;
        totalUnlockedFunds -= amount;

        emit FundsLocked(contributor, amount);
    }

    function unlockContributorFunds(address contributor, uint256 amount) external onlyOwner notTerminated {
        if (amount == 0) revert AmountMustBeGreaterThanZero();
        if (amount > lockedContributions[contributor]) revert InsufficientUnlockedBalance();

        lockedContributions[contributor] -= amount;
        totalUnlockedFunds += amount;

        emit FundsUnlocked(contributor, amount);
    }

    function unlockedBalanceOf(address contributor) public view returns (uint256) {
        return totalContributed[contributor] - lockedContributions[contributor];
    }

    function _registerContributor(address contributor) internal {
        if (!isContributor[contributor]) {
            isContributor[contributor] = true;
            contributors.push(contributor);
        }
    }

    function _contributorsByLockedValue() internal view returns (address[] memory ordered) {
        ordered = new address[](contributors.length);
        for (uint256 i = 0; i < contributors.length; i++) {
            ordered[i] = contributors[i];
        }

        for (uint256 i = 0; i < ordered.length; i++) {
            uint256 maxIndex = i;
            for (uint256 j = i + 1; j < ordered.length; j++) {
                if (lockedContributions[ordered[j]] > lockedContributions[ordered[maxIndex]]) {
                    maxIndex = j;
                }
            }
            if (maxIndex != i) {
                address temp = ordered[i];
                ordered[i] = ordered[maxIndex];
                ordered[maxIndex] = temp;
            }
        }
    }

    function _refundLockedContributors(uint256 baseAmount) internal {
        if (baseAmount == 0) return;

        uint256 remaining = baseAmount;
        address[] memory order = _contributorsByLockedValue();

        for (uint256 i = 0; i < order.length && remaining > 0; i++) {
            address contributor = order[i];
            uint256 locked = lockedContributions[contributor];
            if (locked == 0) continue;

            uint256 refund = remaining < locked ? remaining : locked;
            lockedContributions[contributor] -= refund;
            totalContributed[contributor] -= refund;
            totalUnlockedFunds += refund;
            remaining -= refund;
        }

        if (remaining != 0) revert InsufficientPoolLiquidity();
    }

    function _lockContributorsProportionally(uint256 requiredAmount) internal returns (uint256 totalLocked, uint256 actualDisbursement) {
        uint256 totalDisposable = 0;
        for (uint256 i = 0; i < contributors.length; i++) {
            totalDisposable += unlockedBalanceOf(contributors[i]);
        }

        if (totalDisposable == 0 || requiredAmount > totalDisposable) revert InsufficientPoolLiquidity();

        uint256 remaining = requiredAmount;
        uint256 lastIndex = contributors.length;

        for (uint256 i = 0; i < contributors.length && remaining > 0; i++) {
            address contributor = contributors[i];
            uint256 disposable = unlockedBalanceOf(contributor);
            if (disposable == 0) continue;

            uint256 lockAmount = (disposable * requiredAmount) / totalDisposable;
            if (i == contributors.length - 1) {
                lockAmount = remaining;
            }
            if (lockAmount > disposable) {
                lockAmount = disposable;
            }
            if (lockAmount > remaining) {
                lockAmount = remaining;
            }

            lockedContributions[contributor] += lockAmount;
            totalUnlockedFunds -= lockAmount;
            totalLocked += lockAmount;
            remaining -= lockAmount;
            lastIndex = i;
        }

        uint256 discrepancy = requiredAmount - totalLocked;
        actualDisbursement = requiredAmount - discrepancy;
        return (totalLocked, actualDisbursement);
    }

    function _creditEqualInterestGain(uint256 gainAmount) internal {
        if (gainAmount == 0 || contributors.length == 0) return;

        uint256 equalShare = gainAmount / contributors.length;
        uint256 remainder = gainAmount % contributors.length;

        for (uint256 i = 0; i < contributors.length; i++) {
            uint256 share = equalShare;
            if (remainder > 0) {
                share += 1;
                remainder -= 1;
            }
            pendingInterestGain[contributors[i]] += share;
        }
    }

    function _adjustCollateralPercentage(bool loanSucceeded) internal {
        if (loanSucceeded) {
            collateralPercentage = collateralPercentage > 5 ? collateralPercentage - 5 : MIN_COLLATERAL_PERCENTAGE;
        } else {
            collateralPercentage = collateralPercentage < 95 ? collateralPercentage + 5 : MAX_COLLATERAL_PERCENTAGE;
        }
    }

    function claimInterestGain() external notTerminated {
        uint256 amount = pendingInterestGain[msg.sender];
        if (amount == 0) revert InvalidState();

        pendingInterestGain[msg.sender] = 0;

        (bool sent, ) = payable(msg.sender).call{value: amount}("");
        if (!sent) revert TransferFailed();
    }

    function requestCompensation(uint256 amount) external notTerminated {
        if (amount == 0) revert AmountMustBeGreaterThanZero();
        if (failedLoanCount == 0) revert InvalidState();
        if (amount > lockedContributions[msg.sender]) revert InsufficientUnlockedBalance();
        
        uint256 actualCompensation = amount;
        if (actualCompensation > compensationPoolBalance) {
            actualCompensation = compensationPoolBalance;
        }

        if (actualCompensation == 0) revert CompensationPoolEmpty();

        lockedContributions[msg.sender] -= actualCompensation;
        totalUnlockedFunds += actualCompensation;
        compensationPoolBalance -= actualCompensation;

        (bool sent, ) = payable(msg.sender).call{value: actualCompensation}("");
        if (!sent) revert TransferFailed();

        emit CompensationRequested(msg.sender, actualCompensation);
    }

    function handleRepayment(
        uint256 baseAmount,
        uint256 gainAmount,
        uint256 collateralAmount
    ) external notTerminated {
        if (!authorizedLoanContracts[msg.sender]) revert Unauthorized();

        if (baseAmount > 0) {
            _refundLockedContributors(baseAmount);
        }
        if (gainAmount > 0) {
            _creditEqualInterestGain(gainAmount);
        }
        if (collateralAmount > 0) {
            compensationPoolBalance += collateralAmount;
            emit CompensationPoolFunded(collateralAmount, collateralPercentage);
        }

        _adjustCollateralPercentage(true);
    }

    function handleLoanDefaulted() external notTerminated {
        if (!authorizedLoanContracts[msg.sender]) revert Unauthorized();

        failedLoanCount += 1;
        _adjustCollateralPercentage(false);
    }

    function votingPowerOf(address contributor) external view returns (uint256) {
        return unlockedBalanceOf(contributor);
    }

    function createLoanProposal(
        address borrower,
        string calldata borrowerBtcAddress,
        uint256 principal,
        uint256 interestBps,
        uint256 durationBlocks,
        uint256 votingDurationBlocks
    ) external notTerminated returns (uint256 proposalId) {
        if (borrower == address(0)) revert InvalidAddress();
        if (borrower != msg.sender) revert Unauthorized();
        if (bytes(borrowerBtcAddress).length == 0) revert InvalidBitcoinAddress();
        if (principal == 0 || durationBlocks == 0) revert AmountMustBeGreaterThanZero();
        if (votingDurationBlocks != PROPOSAL_VOTING_PERIOD_BLOCKS) revert InvalidVotingPeriod();

        proposalId = ++proposalCount;
        LoanProposal storage proposal = proposals[proposalId];
        proposal.borrower = borrower;
        proposal.borrowerBtcAddress = borrowerBtcAddress;
        proposal.principal = principal;
        proposal.interestBps = interestBps;
        proposal.durationBlocks = durationBlocks;
        proposal.votingDeadlineBlock = block.number + PROPOSAL_VOTING_PERIOD_BLOCKS;

        emit LoanProposed(
            proposalId,
            borrower,
            borrowerBtcAddress,
            principal,
            interestBps,
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
        if (support) {
            proposal.yesVotes += weight;
        } else {
            proposal.noVotes += weight;
        }

        emit VoteCast(proposalId, msg.sender, support, weight);
    }

    function executeApprovedLoan(uint256 proposalId) external notTerminated returns (address loanAddress) {
        LoanProposal storage proposal = proposals[proposalId];
        if (proposal.borrower == address(0)) revert InvalidProposal();
        if (msg.sender != proposal.borrower) revert Unauthorized();
        if (block.number < proposal.votingDeadlineBlock) revert VotingStillActive();
        if (proposal.executed) revert InvalidState();
        if (proposal.yesVotes <= proposal.noVotes) revert ProposalRejected();

        uint256 borrowerBalanceSats = bitcoinOracle.getBalance(proposal.borrowerBtcAddress);
        uint256 borrowerLiquidityInWei = (borrowerBalanceSats * BTC_TO_ETH_RATE * 1 ether) / SATS_PER_BTC;
        if (borrowerLiquidityInWei < proposal.principal) revert ProposalRejectedByLiquidity();

        if (address(this).balance < proposal.principal) revert InsufficientPoolLiquidity();

        (uint256 lockedAmount, uint256 disbursedAmount) = _lockContributorsProportionally(proposal.principal);
        if (lockedAmount == 0) revert InsufficientPoolLiquidity();

        proposal.executed = true;
        LoanContract loan = new LoanContract(
            address(this),
            proposal.borrower,
            disbursedAmount,
            proposal.interestBps,
            proposal.durationBlocks,
            collateralPercentage
        );

        authorizedLoanContracts[address(loan)] = true;
        loan.fundLoan{value: disbursedAmount}();
        proposal.loanContract = address(loan);
        loanAddress = address(loan);

        emit LoanApproved(proposalId, loanAddress);
    }
}
