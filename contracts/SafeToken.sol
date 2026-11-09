// SPDX-License-Identifier: MIT
pragma solidity 0.8.26;

/// @notice ERC-20 subset used by the network. The selectors are used for
///         SafeToken's low-level calls: the return value declared
///         here is never decoded directly.
interface IERC20Min {
    function balanceOf(address account) external view returns (uint256);
    function transfer(address to, uint256 amount) external returns (bool);
    function transferFrom(address from, address to, uint256 amount) external returns (bool);
}

/// @title SafeToken — transfers that tolerate non-standard tokens
/// @notice USDT on Ethereum returns no value from transfer/transferFrom:
///         a call typed `returns (bool)` would fail while decoding. So we call
///         at low level and accept either an empty response or `true`.
library SafeToken {
    function safeTransfer(IERC20Min token, address to, uint256 value) internal {
        (bool ok, bytes memory data) =
            address(token).call(abi.encodeWithSelector(IERC20Min.transfer.selector, to, value));
        require(ok && (data.length == 0 || abi.decode(data, (bool))), "SafeToken: transfer failed");
    }

    function safeTransferFrom(IERC20Min token, address from, address to, uint256 value) internal {
        (bool ok, bytes memory data) =
            address(token).call(abi.encodeWithSelector(IERC20Min.transferFrom.selector, from, to, value));
        require(ok && (data.length == 0 || abi.decode(data, (bool))), "SafeToken: transferFrom failed");
    }
}
