// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import "../LoanContract.sol";

interface Vm {
    function deal(address account, uint256 balance) external;
    function roll(uint256 blockNumber) external;
}

/// @notice Native Hardhat Solidity unit and fuzz tests, alongside TypeScript scenarios.
contract LoanContractTest is IFundingPool {
    Vm private constant vm = Vm(address(uint160(uint256(keccak256("hevm cheat code")))));
    uint256 private baseReceived;
    uint256 private gainReceived;
    uint256 private collateralReceived;
    uint256 private defaults;

    receive() external payable {}

    function handleRepayment(uint256 base, uint256 gain, uint256 collateral) external {
        baseReceived += base;
        gainReceived += gain;
        collateralReceived += collateral;
    }

    function handleLoanDefaulted() external { defaults += 1; }

    function newLoan(uint256 principal, uint256 rate) private returns (LoanContract loan) {
        vm.deal(address(this), principal * 4 + 100);
        loan = new LoanContract(address(this), address(this), principal, rate, 20, 50);
        loan.fundLoan{value: principal}();
    }

    function testInstallmentContainsPrincipalAndInterest() public {
        LoanContract loan = newLoan(10 ether, 10);
        loan.repay{value: 1.1 ether}();
        require(loan.repaidPrincipal() == 1 ether, "principal component");
        require(loan.repaidInterest() == 0.1 ether, "interest component");
        require(gainReceived == 0.05 ether && collateralReceived == 0.05 ether, "interest split");
    }

    function testSplittingPaymentsPreservesCumulativeRounding() public {
        LoanContract one = newLoan(101, 13);
        LoanContract many = newLoan(101, 13);
        uint256 amount = 71;
        one.repay{value: amount}();
        uint256 oneBase = baseReceived;
        uint256 oneGain = gainReceived;
        uint256 oneCollateral = collateralReceived;
        for (uint256 i = 0; i < amount; i++) many.repay{value: 1}();
        require(many.repaidPrincipal() == one.repaidPrincipal(), "split principal");
        require(many.repaidInterest() == one.repaidInterest(), "split interest");
        require(baseReceived == 2 * oneBase, "base rounding");
        require(gainReceived == 2 * oneGain, "gain rounding");
        require(collateralReceived == 2 * oneCollateral, "collateral rounding");
    }

    function testFuzzRepaymentConservesValue(uint96 rawPrincipal, uint8 rawRate, uint96 rawPayment) public {
        uint256 principal = uint256(rawPrincipal) + 1;
        uint256 rate = uint256(rawRate) % 100 + 1;
        LoanContract loan = newLoan(principal, rate);
        uint256 due = loan.dueAmount();
        uint256 payment = uint256(rawPayment) % (due + 1) + 1;
        loan.repay{value: payment}();
        require(baseReceived + gainReceived + collateralReceived == payment, "value lost");
        require(loan.repaidPrincipal() <= principal, "principal overpaid");
        require(loan.repaidInterest() <= loan.totalInterestAmount(), "interest overpaid");
        if (payment < due) loan.repay{value: due - payment}();
        require(loan.status() == LoanContract.LoanStatus.Repaid, "not closed");
        require(baseReceived == principal, "wrong final principal");
        require(gainReceived + collateralReceived == loan.totalInterestAmount() + (payment > due ? payment - due : 0), "wrong final interest");
    }

    function testDeadlineInclusiveAndLateDefaultIrreversible() public {
        LoanContract onTime = newLoan(1000, 10);
        vm.roll(onTime.dueBlock());
        onTime.repay{value: onTime.dueAmount()}();
        require(onTime.status() == LoanContract.LoanStatus.Repaid, "deadline must be inclusive");
        LoanContract late = newLoan(1000, 10);
        vm.roll(late.dueBlock() + 1);
        late.repay{value: 1100}();
        require(late.status() == LoanContract.LoanStatus.Defaulted, "late success");
        require(defaults == 1, "duplicate default");
    }
}
