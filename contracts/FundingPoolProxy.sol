// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import "@openzeppelin/contracts/proxy/ERC1967/ERC1967Proxy.sol";
import "./FundingPool.sol";

/// @notice ERC-1967 proxy used for the production FundingPool deployment.
/// @dev Initialises the proxy atomically, preventing an uninitialised-pool takeover.
contract FundingPoolProxy is ERC1967Proxy {
    constructor(address implementation, address oracleAddress)
        ERC1967Proxy(implementation, abi.encodeCall(FundingPool.initialize, (oracleAddress)))
    {}
}
