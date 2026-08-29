// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

interface IFundingPool {
    function handleRepayment(uint256 baseAmount, uint256 gainAmount, uint256 collateralAmount) external;
    function handleLoanDefaulted() external;
}

/// @title LoanContract
/// @notice Represents an individual loan managed by the FundingPool.
/// @dev Ephemeral contract deployed for each approved loan. Handles repayment logic and state machine.
contract LoanContract {
    enum LoanStatus {
        Created,
        Funded,
        Repaid,
        Defaulted
    }

    error Unauthorized();
    error InvalidState();
    error InvalidAmount();
    error TransferFailed();
    error LoanNotOverdue();

    address public immutable pool;
    address public immutable borrower;
    uint256 public immutable principal;
    uint256 public immutable interestRate;
    uint256 public immutable dueBlock;
    uint256 public immutable collateralPercentage;

    uint256 public repaidPrincipal;
    uint256 public repaidInterest;

    LoanStatus public status;

    modifier onlyPool() {
        if (msg.sender != pool) revert Unauthorized();
        _;
    }

    /// @notice Initializes the loan contract parameters.
    /// @param poolAddress Address of the managing FundingPool.
    /// @param borrowerAddress Address of the loan applicant.
    /// @param principalAmount Total requested loan in wei.
    /// @param loanInterestRate Interest rate percentage (e.g. 5 for 5%).
    /// @param durationBlocks Number of blocks before the loan is considered overdue.
    /// @param loanCollateralPercentage Percentage of interest redirected to the compensation pool.
    constructor(
        address poolAddress,
        address borrowerAddress,
        uint256 principalAmount,
        uint256 loanInterestRate,
        uint256 durationBlocks,
        uint256 loanCollateralPercentage
    ) {
        if (poolAddress == address(0) || borrowerAddress == address(0)) revert InvalidAmount();
        if (principalAmount == 0) revert InvalidAmount();

        pool = poolAddress;
        borrower = borrowerAddress;
        principal = principalAmount;
        interestRate = loanInterestRate;
        collateralPercentage = loanCollateralPercentage;
        dueBlock = block.number + durationBlocks;
        status = LoanStatus.Created;
    }

    /// @notice Calculates the total amount due for repayment.
    /// @return The sum of the principal and total interest.
    function dueAmount() public view returns (uint256) {
        return principal + totalInterestAmount();
    }

    /// @notice Calculates the total interest amount to be paid on the principal.
    /// @return Total interest in wei.
    function totalInterestAmount() public view returns (uint256) {
        return (principal * interestRate) / 100;
    }

    /// @notice Funds the loan by transferring the principal to the borrower.
    /// @dev Can only be called by the FundingPool once.
    function fundLoan() external payable onlyPool {
        if (status != LoanStatus.Created) revert InvalidState();
        if (msg.value != principal) revert InvalidAmount();

        status = LoanStatus.Funded;

        (bool sent, ) = payable(borrower).call{value: msg.value}("");
        if (!sent) revert TransferFailed();
    }

    /// @notice Handles partial or full repayments from the borrower.
    /// @dev Routes payments, splitting them into base (principal) and gain (interest), 
    /// and forwards them to the FundingPool.
    function repay() external payable {
        if (msg.sender != borrower) revert Unauthorized();
        if (status != LoanStatus.Funded && status != LoanStatus.Defaulted) revert InvalidState();
        if (msg.value == 0) revert InvalidAmount();

        // A loan that was still unpaid after its expiry is failed, including
        // when the first late transaction is only a partial repayment.
        if (status == LoanStatus.Funded && block.number > dueBlock) {
            status = LoanStatus.Defaulted;
            IFundingPool(pool).handleLoanDefaulted();
        }

        uint256 payment = msg.value;
        
        uint256 remainingPrincipal = principal - repaidPrincipal;
        uint256 baseAmount = (payment <= remainingPrincipal) ? payment : remainingPrincipal;
        
        repaidPrincipal += baseAmount;
        uint256 leftoverAfterPrincipal = payment - baseAmount;

        uint256 expectedInterest = totalInterestAmount();
        uint256 remainingInterest = expectedInterest - repaidInterest;
        
        uint256 interestPaid = (leftoverAfterPrincipal <= remainingInterest) ? leftoverAfterPrincipal : remainingInterest;
        repaidInterest += interestPaid;
        
        uint256 excessAmount = leftoverAfterPrincipal - interestPaid;

        uint256 currentCollateralAmount = (interestPaid * collateralPercentage) / 100;
        uint256 gainAmount = interestPaid - currentCollateralAmount;

        currentCollateralAmount += excessAmount;

        if (repaidPrincipal == principal && repaidInterest == expectedInterest && status == LoanStatus.Funded) {
            status = LoanStatus.Repaid;
        }

        (bool sent, ) = payable(pool).call{value: msg.value}("");
        if (!sent) revert TransferFailed();

        IFundingPool(pool).handleRepayment(baseAmount, gainAmount, currentCollateralAmount);
    }

    /// @notice Marks the loan as defaulted if it is overdue.
    /// @dev Reverts if the current block is before or equal to the dueBlock. Notifies the FundingPool.
    function markDefaulted() external {
        if (status != LoanStatus.Funded) revert InvalidState();
        if (block.number <= dueBlock) revert LoanNotOverdue();

        status = LoanStatus.Defaulted;
        IFundingPool(pool).handleLoanDefaulted();
    }
}
