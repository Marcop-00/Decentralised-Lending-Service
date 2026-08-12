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
    uint256 public immutable interestBps;
    uint256 public immutable dueBlock;
    uint256 public immutable collateralPercentage;

    // Nuove variabili per tracciare i rimborsi parziali
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
        uint256 interestBasisPoints,
        uint256 durationBlocks,
        uint256 loanCollateralPercentage
    ) {
        if (poolAddress == address(0) || borrowerAddress == address(0)) revert InvalidAmount();
        if (principalAmount == 0) revert InvalidAmount();

        pool = poolAddress;
        borrower = borrowerAddress;
        principal = principalAmount;
        interestBps = interestBasisPoints;
        collateralPercentage = loanCollateralPercentage;
        dueBlock = block.number + durationBlocks;
        status = LoanStatus.Created;
    }

    function dueAmount() public view returns (uint256) {
        return principal + totalInterestAmount();
    }

    function totalInterestAmount() public view returns (uint256) {
        return (principal * interestBps) / 10_000;
    }

    function fundLoan() external payable onlyPool {
        if (status != LoanStatus.Created) revert InvalidState();
        if (msg.value != principal) revert InvalidAmount();

        status = LoanStatus.Funded;

        (bool sent, ) = payable(borrower).call{value: msg.value}("");
        if (!sent) revert TransferFailed();
    }

    function repay() external payable {
        // 1. Solo il richiedente originale può ripagare il prestito
        if (msg.sender != borrower) revert Unauthorized();
        
        // 2. Può ripagare se il prestito è attivo o fallito
        if (status != LoanStatus.Funded && status != LoanStatus.Defaulted) revert InvalidState();
        if (msg.value == 0) revert InvalidAmount();

        uint256 payment = msg.value;
        
        // Calcolo di quanto manca da pagare per il capitale
        uint256 remainingPrincipal = principal - repaidPrincipal;
        uint256 baseAmount = (payment <= remainingPrincipal) ? payment : remainingPrincipal;
        
        repaidPrincipal += baseAmount;
        uint256 leftoverAfterPrincipal = payment - baseAmount;

        // Calcolo di quanto manca da pagare per gli interessi
        uint256 expectedInterest = totalInterestAmount();
        uint256 remainingInterest = expectedInterest - repaidInterest;
        
        uint256 interestPaid = (leftoverAfterPrincipal <= remainingInterest) ? leftoverAfterPrincipal : remainingInterest;
        repaidInterest += interestPaid;
        
        // 3. Tutto l'eccesso oltre al totale dovuto va alla compensation pool
        uint256 excessAmount = leftoverAfterPrincipal - interestPaid;

        // Suddivisione degli interessi pagati in questa transazione
        uint256 currentCollateralAmount = (interestPaid * collateralPercentage) / 100;
        uint256 gainAmount = interestPaid - currentCollateralAmount;

        // Aggiungiamo l'eventuale eccesso pagato al collaterale (che andrà alla compensation pool)
        currentCollateralAmount += excessAmount;

        // 4. Se tutto è stato ripagato, aggiorniamo lo stato (solo se non era già fallito)
        if (repaidPrincipal == principal && repaidInterest == expectedInterest) {
            if (status == LoanStatus.Funded) {
                status = LoanStatus.Repaid;
            }
        }

        // Invia i fondi alla pool
        (bool sent, ) = payable(pool).call{value: msg.value}("");
        if (!sent) revert TransferFailed();

        // Segnala alla pool le quote esatte
        IFundingPool(pool).handleRepayment(baseAmount, gainAmount, currentCollateralAmount);
    }

    function markDefaulted() external onlyPool {
        if (status != LoanStatus.Funded) revert InvalidState();
        if (block.number < dueBlock) revert LoanNotOverdue();

        status = LoanStatus.Defaulted;
        IFundingPool(pool).handleLoanDefaulted();
    }
}