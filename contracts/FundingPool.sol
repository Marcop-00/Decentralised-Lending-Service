// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import "./LoanContract.sol";
import "./BitcoinOracle.sol";

contract FundingPool {
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

    event ContributionAdded(address indexed contributor, uint256 amount);
    event ContributionWithdrawn(address indexed contributor, uint256 amount);
    event FundsLocked(address indexed contributor, uint256 amount);
    event FundsUnlocked(address indexed contributor, uint256 amount);
    event LoanProposed(
        uint256 indexed proposalId,
        address indexed borrower,
        string borrowerBtcAddress,
        uint256 principal,
        uint256 interestBps,
        uint256 durationSeconds,
        uint256 votingDeadline
    );
    event VoteCast(uint256 indexed proposalId, address indexed voter, bool support, uint256 weight);
    event LoanApproved(uint256 indexed proposalId, address indexed loanContract);

    struct LoanProposal {
        address borrower;
        string borrowerBtcAddress;
        uint256 principal;
        uint256 interestBps;
        uint256 durationSeconds;
        uint256 votingDeadline;
        uint256 yesVotes;
        uint256 noVotes;
        bool executed;
        address loanContract;
    }

    mapping(address => uint256) public totalContributed;
    mapping(address => uint256) public lockedContributions;
    mapping(uint256 => LoanProposal) public proposals;
    mapping(uint256 => mapping(address => bool)) public hasVoted;

    uint256 public proposalCount;
    uint256 public totalUnlockedFunds;
    address public immutable owner;
    BitcoinOracle public immutable bitcoinOracle;

    uint256 public constant BTC_TO_ETH_RATE = 30;
    uint256 public constant SATS_PER_BTC = 100_000_000;
    uint256 public constant MIN_DEPOSIT_WEI = 100_000;

    modifier onlyOwner() {
        if (msg.sender != owner) revert Unauthorized();
        _;
    }

    receive() external payable {}

    constructor(address oracleAddress) {
        if (oracleAddress == address(0)) revert InvalidAddress();
        owner = msg.sender;
        bitcoinOracle = BitcoinOracle(oracleAddress);
    }

    function contribute() external payable {
        if (msg.value < MIN_DEPOSIT_WEI) revert AmountMustBeGreaterThanZero();

        totalContributed[msg.sender] += msg.value;
        totalUnlockedFunds += msg.value;

        emit ContributionAdded(msg.sender, msg.value);
    }

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

    function lockContributorFunds(address contributor, uint256 amount) external onlyOwner {
        if (amount == 0) revert AmountMustBeGreaterThanZero();

        uint256 unlocked = unlockedBalanceOf(contributor);
        if (amount > unlocked) revert InsufficientUnlockedBalance();

        lockedContributions[contributor] += amount;
        totalUnlockedFunds -= amount;

        emit FundsLocked(contributor, amount);
    }

    function unlockContributorFunds(address contributor, uint256 amount) external onlyOwner {
        if (amount == 0) revert AmountMustBeGreaterThanZero();
        if (amount > lockedContributions[contributor]) revert InsufficientUnlockedBalance();

        lockedContributions[contributor] -= amount;
        totalUnlockedFunds += amount;

        emit FundsUnlocked(contributor, amount);
    }

    function unlockedBalanceOf(address contributor) public view returns (uint256) {
        return totalContributed[contributor] - lockedContributions[contributor];
    }

    function votingPowerOf(address contributor) external view returns (uint256) {
        return unlockedBalanceOf(contributor);
    }

    function createLoanProposal(
        address borrower,
        string calldata borrowerBtcAddress,
        uint256 principal,
        uint256 interestBps,
        uint256 durationSeconds,
        uint256 votingDurationSeconds
    ) external returns (uint256 proposalId) {
        if (borrower == address(0)) revert InvalidAddress();
        if (borrower != msg.sender) revert Unauthorized();
        if (bytes(borrowerBtcAddress).length == 0) revert InvalidBitcoinAddress();
        if (principal == 0 || durationSeconds == 0 || votingDurationSeconds == 0) {
            revert AmountMustBeGreaterThanZero();
        }

        proposalId = ++proposalCount;
        LoanProposal storage proposal = proposals[proposalId];
        proposal.borrower = borrower;
        proposal.borrowerBtcAddress = borrowerBtcAddress;
        proposal.principal = principal;
        proposal.interestBps = interestBps;
        proposal.durationSeconds = durationSeconds;
        proposal.votingDeadline = block.timestamp + votingDurationSeconds;

        emit LoanProposed(
            proposalId,
            borrower,
            borrowerBtcAddress,
            principal,
            interestBps,
            durationSeconds,
            proposal.votingDeadline
        );
    }

    function voteOnProposal(uint256 proposalId, bool support) external {
        LoanProposal storage proposal = proposals[proposalId];
        if (proposal.borrower == address(0)) revert InvalidProposal();
        if (block.timestamp > proposal.votingDeadline) revert VotingClosed();
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

    function executeApprovedLoan(uint256 proposalId) external returns (address loanAddress) {
        LoanProposal storage proposal = proposals[proposalId];
        if (proposal.borrower == address(0)) revert InvalidProposal();
        if (msg.sender != proposal.borrower) revert Unauthorized();
        if (block.timestamp <= proposal.votingDeadline) revert VotingStillActive();
        if (proposal.executed) revert InvalidState();
        if (proposal.yesVotes <= proposal.noVotes) revert ProposalRejected();

        uint256 borrowerBalanceSats = bitcoinOracle.getBalanceSats(proposal.borrowerBtcAddress);
        uint256 borrowerLiquidityInWei = (borrowerBalanceSats * BTC_TO_ETH_RATE * 1 ether) / SATS_PER_BTC;
        if (borrowerLiquidityInWei < proposal.principal) revert ProposalRejectedByLiquidity();

        if (address(this).balance < proposal.principal) revert InsufficientPoolLiquidity();

        proposal.executed = true;
        LoanContract loan = new LoanContract(
            address(this),
            proposal.borrower,
            proposal.principal,
            proposal.interestBps,
            proposal.durationSeconds
        );

        loan.fundLoan{value: proposal.principal}();
        proposal.loanContract = address(loan);
        loanAddress = address(loan);

        emit LoanApproved(proposalId, loanAddress);
    }
}
