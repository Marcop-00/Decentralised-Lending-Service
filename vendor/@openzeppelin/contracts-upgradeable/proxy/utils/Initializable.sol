// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

abstract contract Initializable {
    bool private _initialized;
    bool private _initializing;

    modifier initializer() {
        require(!_initialized, "Initializable: contract already initialized");
        require(!_initializing, "Initializable: reentrant initialization");

        _initializing = true;
        _;
        _initializing = false;
        _initialized = true;
    }

    modifier onlyInitializing() {
        require(_initializing, "Initializable: contract not initializing");
        _;
    }

    function _isInitialized() internal view returns (bool) {
        return _initialized;
    }
}
