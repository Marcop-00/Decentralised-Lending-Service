// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import "../../access/OwnableUpgradeable.sol";
import "./Initializable.sol";

abstract contract UUPSUpgradeable is Initializable {
    function __UUPSUpgradeable_init() internal onlyInitializing {
        // no-op for this minimal compatibility shim
    }

    function _authorizeUpgrade(address newImplementation) internal virtual;
}
