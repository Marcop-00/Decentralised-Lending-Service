// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import "@openzeppelin/contracts/access/Ownable.sol";

contract BitcoinOracle is Ownable {
    uint256 public immutable minFee;
    mapping(string => uint256) private balances;

    // Evento ascoltato dallo script Python
    event UpdateRequested(string btcAddress, address indexed requester, uint256 fee);
    event BalanceUpdated(string btcAddress, uint256 balanceInSatoshi);

    error InsufficientFee();

    constructor(uint256 _minFee) Ownable(msg.sender) {
        minFee = _minFee;
    }

    // 1. Il richiedente (applicant) chiama questa funzione e paga la fee
    function requestUpdate(string calldata btcAddress) external payable {
        if (msg.value < minFee) revert InsufficientFee();
        
        // Emette l'evento che farà scattare lo script Python
        emit UpdateRequested(btcAddress, msg.sender, msg.value);
    }

    // 2. Lo script Python elabora il blocco e chiama questa funzione
    function update(string calldata btcAddress, uint256 balanceInSatoshi) external onlyOwner {
        balances[btcAddress] = balanceInSatoshi;
        emit BalanceUpdated(btcAddress, balanceInSatoshi);
    }

    // 3. Il FundingPool legge il bilancio da qui
    function getBalance(string calldata btcAddress) external view returns (uint256) {
        return balances[btcAddress];
    }
}