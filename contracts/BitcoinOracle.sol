// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import "@openzeppelin/contracts/access/Ownable.sol";

/// @title BitcoinOracle
/// @notice Simulates a cross-chain oracle to verify a borrower's Bitcoin collateral.
/// @dev A Python script (Oracle Service) listens to events and pushes data back.
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
    /// @notice Requests a balance update for a specific Bitcoin address.
    /// @param btcAddress The Bitcoin address (e.g. starting with bc1 or 1) to check.
    function requestUpdate(string calldata btcAddress) external payable {
        if (msg.value < minFee) revert InsufficientFee();
        
        // Emits the event that will trigger the Python script
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