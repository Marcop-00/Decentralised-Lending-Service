// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import "@openzeppelin/contracts/access/Ownable.sol";

contract BitcoinOracle is Ownable {
    uint256 public immutable minFee;
    mapping(string => uint256) private balances;

    // Event listened to by the Python script
    event UpdateRequested(string btcAddress, address indexed requester, uint256 fee);
    event BalanceUpdated(string btcAddress, uint256 balanceInSatoshi);

    error InsufficientFee();

    constructor(uint256 _minFee) Ownable(msg.sender) {
        minFee = _minFee;
    }

    // 1. The applicant calls this function and pays the fee
    function requestUpdate(string calldata btcAddress) external payable {
        if (msg.value < minFee) revert InsufficientFee();
        
        // Emette l'evento che farà scattare lo script Python
        emit UpdateRequested(btcAddress, msg.sender, msg.value);
    }

    // 2. The Python script processes the block and calls this function
    function update(string calldata btcAddress, uint256 balanceInSatoshi) external onlyOwner {
        balances[btcAddress] = balanceInSatoshi;
        emit BalanceUpdated(btcAddress, balanceInSatoshi);
    }

    // 3. The FundingPool reads the balance from here
    function getBalance(string calldata btcAddress) external view returns (uint256) {
        return balances[btcAddress];
    }
}