// SPDX-License-Identifier: MIT
pragma solidity 0.8.26;

/// @title MockUSDC — stablecoin de test, 6 décimales
/// @notice RÉSERVÉ AU TESTNET / DEVNET. Le mint est ouvert à tous pour que
///         chacun puisse simuler des revenus. Ne JAMAIS déployer en production :
///         sur mainnet, utiliser le vrai USDC de Circle.
contract MockUSDC {
    string public constant name = "Mock USD Coin";
    string public constant symbol = "mUSDC";
    uint8 public constant decimals = 6;

    uint256 public totalSupply;
    mapping(address => uint256) public balanceOf;
    mapping(address => mapping(address => uint256)) public allowance;

    event Transfer(address indexed from, address indexed to, uint256 value);
    event Approval(address indexed holder, address indexed spender, uint256 value);

    function mint(address to, uint256 amount) external {
        require(to != address(0), "mUSDC: mint to zero");
        totalSupply += amount;
        balanceOf[to] += amount;
        emit Transfer(address(0), to, amount);
    }

    function transfer(address to, uint256 value) external returns (bool) {
        _transfer(msg.sender, to, value);
        return true;
    }

    function approve(address spender, uint256 value) external returns (bool) {
        allowance[msg.sender][spender] = value;
        emit Approval(msg.sender, spender, value);
        return true;
    }

    function transferFrom(address from, address to, uint256 value) external returns (bool) {
        uint256 allowed = allowance[from][msg.sender];
        if (allowed != type(uint256).max) {
            require(allowed >= value, "mUSDC: allowance exceeded");
            allowance[from][msg.sender] = allowed - value;
        }
        _transfer(from, to, value);
        return true;
    }

    function _transfer(address from, address to, uint256 value) internal {
        require(to != address(0), "mUSDC: transfer to zero");
        uint256 fromBalance = balanceOf[from];
        require(fromBalance >= value, "mUSDC: balance too low");
        balanceOf[from] = fromBalance - value;
        balanceOf[to] += value;
        emit Transfer(from, to, value);
    }
}
