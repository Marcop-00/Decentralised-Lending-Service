// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

/// @title ReentrancyVulnerableLoan
/// @notice A simplified contract designed to demonstrate a reentrancy vulnerability.
/// @dev This contract violates the Checks-Effects-Interactions pattern.
contract ReentrancyVulnerableLoan {
    error InvalidAmount();
    error TransferFailed();

    mapping(address => uint256) public balances;

    function deposit() external payable {
        if (msg.value == 0) revert InvalidAmount();
        balances[msg.sender] += msg.value;
    }

    /// @notice Withdraws the caller's entire balance.
    /// @dev Vulnerable to reentrancy because the external call happens before the state update.
    function withdraw() external {
        uint256 amount = balances[msg.sender];
        if (amount == 0) revert InvalidAmount();

        (bool sent, ) = payable(msg.sender).call{value: amount}("");
        if (!sent) revert TransferFailed();

        balances[msg.sender] = 0;
    }
}
