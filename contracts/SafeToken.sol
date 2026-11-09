// SPDX-License-Identifier: MIT
pragma solidity 0.8.26;

/// @notice Sous-ensemble ERC-20 utilisé par le réseau. Les sélecteurs servent
///         aux appels bas niveau de SafeToken : la valeur de retour déclarée
///         ici n'est jamais décodée directement.
interface IERC20Min {
    function balanceOf(address account) external view returns (uint256);
    function transfer(address to, uint256 amount) external returns (bool);
    function transferFrom(address from, address to, uint256 amount) external returns (bool);
}

/// @title SafeToken — transferts tolérants aux jetons non standard
/// @notice USDT sur Ethereum ne renvoie aucune valeur sur transfer/transferFrom :
///         un appel typé `returns (bool)` échouerait au décodage. On appelle
///         donc en bas niveau et on accepte une réponse vide ou `true`.
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
