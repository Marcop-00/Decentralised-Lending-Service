// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import "../FundingPool.sol";

/// @notice Compatible V2 used to demonstrate an actual implementation upgrade.
contract FundingPoolV2 is FundingPool {
    function version() external pure returns (uint256) {
        return 2;
    }
}
