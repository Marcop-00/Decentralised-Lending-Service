// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

/// @dev Memory merge sort: O(n log n), descending initial share then address.
library ContributorOrder {
    struct Position {
        address account;
        uint256 initialShare;
    }

    function sort(Position[] memory positions) internal pure {
        Position[] memory scratch = new Position[](positions.length);
        _sort(positions, scratch, 0, positions.length);
    }

    function _sort(Position[] memory positions, Position[] memory scratch, uint256 lo, uint256 hi) private pure {
        if (hi - lo < 2) return;
        uint256 mid = lo + (hi - lo) / 2;
        _sort(positions, scratch, lo, mid);
        _sort(positions, scratch, mid, hi);
        uint256 left = lo;
        uint256 right = mid;
        for (uint256 out = lo; out < hi; out++) {
            bool takeLeft = right == hi || (left < mid && _before(positions[left], positions[right]));
            scratch[out] = takeLeft ? positions[left++] : positions[right++];
        }
        for (uint256 i = lo; i < hi; i++) positions[i] = scratch[i];
    }

    function _before(Position memory a, Position memory b) private pure returns (bool) {
        return a.initialShare > b.initialShare
            || (a.initialShare == b.initialShare && uint160(a.account) >= uint160(b.account));
    }
}
