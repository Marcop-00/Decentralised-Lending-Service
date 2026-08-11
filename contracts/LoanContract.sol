// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

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
    uint256 public immutable interestBps;
    uint256 public immutable dueTimestamp;

    LoanStatus public status;

    modifier onlyPool() {
        if (msg.sender != pool) revert Unauthorized();
        _;
    }

    constructor(
        address poolAddress,
        address borrowerAddress,
        uint256 principalAmount,
        uint256 interestBasisPoints,
        uint256 durationSeconds
    ) {
        if (poolAddress == address(0) || borrowerAddress == address(0)) revert InvalidAmount();
        if (principalAmount == 0) revert InvalidAmount();

        pool = poolAddress;
        borrower = borrowerAddress;
        principal = principalAmount;
        interestBps = interestBasisPoints;
        dueTimestamp = block.timestamp + durationSeconds;
        status = LoanStatus.Created;
    }

    function dueAmount() public view returns (uint256) {
        return principal + (principal * interestBps) / 10_000;
    }

    function fundLoan() external payable onlyPool {
        if (status != LoanStatus.Created) revert InvalidState();
        if (msg.value != principal) revert InvalidAmount();

        status = LoanStatus.Funded;

        (bool sent, ) = payable(borrower).call{value: msg.value}("");
        if (!sent) revert TransferFailed();
    }

    function repay() external payable {
        if (status != LoanStatus.Funded) revert InvalidState();
        if (msg.value != dueAmount()) revert InvalidAmount();

        status = LoanStatus.Repaid;

        (bool sent, ) = payable(pool).call{value: msg.value}("");
        if (!sent) revert TransferFailed();
    }

    function markDefaulted() external onlyPool {
        if (status != LoanStatus.Funded) revert InvalidState();
        if (block.timestamp < dueTimestamp) revert LoanNotOverdue();

        status = LoanStatus.Defaulted;
    }
}
