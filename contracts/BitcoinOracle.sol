// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import "@openzeppelin/contracts/access/Ownable.sol";

/// @title BitcoinOracle
/// @notice Simulates a cross-chain oracle to verify a borrower's Bitcoin collateral.
/// @dev A Python script (Oracle Service) listens to events and pushes data back.
contract BitcoinOracle is Ownable {
    // Measured cost of update() with a new storage slot on the configured EVM.
    // The trace fixes the gas price factor at 0.1 gwei.
    uint256 public constant UPDATE_GAS_ESTIMATE = 48_799;
    uint256 public constant ORACLE_GAS_PRICE_WEI = 0.1 gwei;
    uint256 public immutable minFee;
    mapping(string => uint256) private balances;

    // Event listened to by the Python script
    event UpdateRequested(string btcAddress, address indexed requester, uint256 fee);
    event BalanceUpdated(string btcAddress, uint256 balanceInSatoshi);

    error InsufficientFee();
    error TransferFailed();
    error InvalidRecipient();

    constructor() Ownable(msg.sender) {
        minFee = UPDATE_GAS_ESTIMATE * ORACLE_GAS_PRICE_WEI;
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
    /// @notice Updates the stored Bitcoin balance for a specific address.
    /// @dev Only callable by the oracle owner (the Python backend).
    /// @param btcAddress The checked Bitcoin address.
    /// @param balanceInSatoshi The confirmed balance in satoshis.
    function update(string calldata btcAddress, uint256 balanceInSatoshi) external onlyOwner {
        balances[btcAddress] = balanceInSatoshi;
        emit BalanceUpdated(btcAddress, balanceInSatoshi);
    }

    // 3. The FundingPool reads the balance from here
    /// @notice Retrieves the latest known Bitcoin balance for an address.
    /// @param btcAddress The Bitcoin address to check.
    /// @return The stored balance in satoshi (1 BTC = 10^8 satoshi).
    function getBalance(string calldata btcAddress) external view returns (uint256) {
        return balances[btcAddress];
    }

    /// @notice Lets the trusted oracle operator collect update-request fees.
    function withdrawFees(address payable recipient) external onlyOwner {
        if (recipient == address(0)) revert InvalidRecipient();
        (bool sent, ) = recipient.call{value: address(this).balance}("");
        if (!sent) revert TransferFailed();
    }
}
