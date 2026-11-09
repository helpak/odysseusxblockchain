// SPDX-License-Identifier: MIT
pragma solidity 0.8.26;

/// @title MockUSDT — imitation fidèle des particularités de l'USDT Ethereum
/// @notice RÉSERVÉ AUX TESTS / TESTNETS. Reproduit ce qui casse les intégrations
///         naïves de l'USDT réel :
///           - 6 décimales ;
///           - transfer / transferFrom / approve ne renvoient AUCUNE valeur ;
///           - un frais de transfert optionnel (l'USDT réel en a un, à 0 aujourd'hui).
///         Mint ouvert à tous : ne JAMAIS déployer en production.
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
        totalSupply -= fee; // frais brûlé, comme s'il partait chez l'émetteur
        emit Transfer(from, to, value - fee);
    }
}
