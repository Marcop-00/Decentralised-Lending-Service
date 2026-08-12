// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

contract ReentrancyVulnerableLoan {
    error InvalidAmount();
    error TransferFailed();

    mapping(address => uint256) public balances;

    function deposit() external payable {
        if (msg.value == 0) revert InvalidAmount();
        balances[msg.sender] += msg.value;
    }

    function withdraw() external {
        uint256 amount = balances[msg.sender];
        if (amount == 0) revert InvalidAmount();

        (bool sent, ) = payable(msg.sender).call{value: amount}("");
        if (!sent) revert TransferFailed();

        balances[msg.sender] = 0;
    }
}
