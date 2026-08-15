// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

interface IFundingPool {
    function handleRepayment(uint256 baseAmount, uint256 gainAmount, uint256 collateralAmount) external;
    function handleLoanDefaulted() external;
}

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

    function dueAmount() public view returns (uint256) {
        return principal + totalInterestAmount();
    }

    function totalInterestAmount() public view returns (uint256) {
        return (principal * interestRate) / 100;
    }

    function fundLoan() external payable onlyPool {
        if (status != LoanStatus.Created) revert InvalidState();
        if (msg.value != principal) revert InvalidAmount();

        status = LoanStatus.Funded;

        (bool sent, ) = payable(borrower).call{value: msg.value}("");
        if (!sent) revert TransferFailed();
    }

    function repay() external payable {
        if (msg.sender != borrower) revert Unauthorized();
        if (status != LoanStatus.Funded && status != LoanStatus.Defaulted) revert InvalidState();
        if (msg.value == 0) revert InvalidAmount();

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

        if (repaidPrincipal == principal && repaidInterest == expectedInterest) {
            if (status == LoanStatus.Funded) {
                status = LoanStatus.Repaid;
            }
        }

        (bool sent, ) = payable(pool).call{value: msg.value}("");
        if (!sent) revert TransferFailed();

        IFundingPool(pool).handleRepayment(baseAmount, gainAmount, currentCollateralAmount);
    }

    function markDefaulted() external onlyPool {
        if (status != LoanStatus.Funded) revert InvalidState();
        if (block.number < dueBlock) revert LoanNotOverdue();

        status = LoanStatus.Defaulted;
        IFundingPool(pool).handleLoanDefaulted();
    }
}