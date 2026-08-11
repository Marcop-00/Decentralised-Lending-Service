// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

contract BitcoinOracle {
    error FeeTooLow();
    error Unauthorized();
    error InvalidAmount();
    error TransferFailed();

    event BalanceUpdated(string indexed btcAddress, uint256 balanceSats, address indexed updater, uint256 feePaid);
    event FeeWithdrawn(address indexed recipient, uint256 amount);

    uint256 public immutable minimumUpdateFeeWei;
    address public immutable owner;

    // Stored in satoshis (1 BTC = 100,000,000 sats).
    mapping(string => uint256) private btcBalancesSats;

    modifier onlyOwner() {
        if (msg.sender != owner) revert Unauthorized();
        _;
    }

    constructor(uint256 minFeeWei) {
        if (minFeeWei == 0) revert InvalidAmount();
        owner = msg.sender;
        minimumUpdateFeeWei = minFeeWei;
    }

    function updateBalance(string calldata btcAddress, uint256 balanceSats) external payable {
        if (msg.value < minimumUpdateFeeWei) revert FeeTooLow();
        btcBalancesSats[btcAddress] = balanceSats;
        emit BalanceUpdated(btcAddress, balanceSats, msg.sender, msg.value);
    }

    function getBalanceSats(string calldata btcAddress) external view returns (uint256) {
        return btcBalancesSats[btcAddress];
    }

    function withdrawFees(address payable recipient, uint256 amount) external onlyOwner {
        if (recipient == address(0) || amount == 0) revert InvalidAmount();
        if (amount > address(this).balance) revert InvalidAmount();

        (bool sent, ) = recipient.call{value: amount}("");
        if (!sent) revert TransferFailed();

        emit FeeWithdrawn(recipient, amount);
    }
}
