// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import "../FundingPool.sol";

/// @notice TEST ONLY: the real pool with an intentionally vulnerable withdrawal.
/// @dev Never used by setup.py. Deploy behind FundingPoolProxy for the attack demo.
contract FundingPoolVulnerable is FundingPool {
    function withdraw(uint256 amount) external override {
        if (amount == 0) revert AmountMustBeGreaterThanZero();
        if (amount > unlockedBalanceOf(msg.sender)) revert InsufficientUnlockedBalance();

        // These cached balances stay unchanged during recursive withdrawals.
        uint256 positionBefore = totalContributed[msg.sender];
        uint256 availableBefore = totalUnlockedFunds;
        (bool sent, ) = payable(msg.sender).call{value: amount}("");
        if (!sent) revert TransferFailed();

        // Intentionally broken: stale assignments AFTER the external call.
        // A checked subtraction of the live balance could instead revert and
        // undo the attack in Solidity 0.8; this variant demonstrates real theft.
        totalContributed[msg.sender] = positionBefore - amount;
        totalUnlockedFunds = availableBefore - amount;
        _unregisterEmptyContributor(msg.sender);
        emit ContributionWithdrawn(msg.sender, amount);
    }
}
