// SPDX-License-Identifier: MIT
pragma solidity 0.8.26;

/// @title MockUSDT — faithful imitation of the quirks of Ethereum USDT
/// @notice FOR TESTS / TESTNETS ONLY. Reproduces what breaks naive
///         integrations of the real USDT:
///           - 6 decimals;
///           - transfer / transferFrom / approve return NO value;
///           - an optional transfer fee (the real USDT has one, set to 0 today).
///         Mint is open to everyone: NEVER deploy to production.
contract MockUSDT {
    string public constant name = "Mock Tether USD";
    string public constant symbol = "mUSDT";
    uint8 public constant decimals = 6;

    uint256 public totalSupply;
    uint256 public feeBps;
    mapping(address => uint256) public balanceOf;
    mapping(address => mapping(address => uint256)) public allowance;

    event Transfer(address indexed from, address indexed to, uint256 value);
    event Approval(address indexed holder, address indexed spender, uint256 value);

    function mint(address to, uint256 amount) external {
        totalSupply += amount;
        balanceOf[to] += amount;
        emit Transfer(address(0), to, amount);
    }

    function setFeeBps(uint256 bps) external {
        require(bps <= 1_000, "mUSDT: fee too high");
        feeBps = bps;
    }

    function transfer(address to, uint256 value) external {
        _transfer(msg.sender, to, value);
    }

    function approve(address spender, uint256 value) external {
        allowance[msg.sender][spender] = value;
        emit Approval(msg.sender, spender, value);
    }

    function transferFrom(address from, address to, uint256 value) external {
        uint256 allowed = allowance[from][msg.sender];
        if (allowed != type(uint256).max) {
            require(allowed >= value, "mUSDT: allowance exceeded");
            allowance[from][msg.sender] = allowed - value;
        }
        _transfer(from, to, value);
    }

    function _transfer(address from, address to, uint256 value) private {
        require(balanceOf[from] >= value, "mUSDT: balance too low");
        uint256 fee = (value * feeBps) / 10_000;
        balanceOf[from] -= value;
        balanceOf[to] += value - fee;
        totalSupply -= fee; // fee burned, as if it went to the issuer
        emit Transfer(from, to, value - fee);
    }
}
