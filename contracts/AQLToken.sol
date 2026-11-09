// SPDX-License-Identifier: MIT
pragma solidity 0.8.26;

/// @title AQL — the network's native token
/// @notice Supply capped at 1 billion. No premine: every AQL is created by
///         the network contract (AQLNetwork) as a reward for verified work.
///         The deployer can do exactly one thing, exactly once: designate
///         that contract as the minter. After that, nobody has any power
///         over the token.
contract AQLToken {
    string public constant name = "AQL";
    string public constant symbol = "AQL";
    uint8 public constant decimals = 18;

    uint256 public constant MAX_SUPPLY = 1_000_000_000e18;

    uint256 public totalSupply;
    address public minter;
    address private immutable _deployer;

    mapping(address => uint256) public balanceOf;
    mapping(address => mapping(address => uint256)) public allowance;

    event Transfer(address indexed from, address indexed to, uint256 value);
    event Approval(address indexed holder, address indexed spender, uint256 value);
    event MinterSet(address indexed minter);

    constructor() {
        _deployer = msg.sender;
    }

    /// @notice Designates the minter, once and irreversibly.
    function initMinter(address minter_) external {
        require(msg.sender == _deployer, "AQL: not deployer");
        require(minter == address(0), "AQL: minter already set");
        require(minter_ != address(0), "AQL: minter is zero");
        minter = minter_;
        emit MinterSet(minter_);
    }

    function mint(address to, uint256 amount) external {
        require(msg.sender == minter, "AQL: not minter");
        require(to != address(0), "AQL: mint to zero");
        require(totalSupply + amount <= MAX_SUPPLY, "AQL: max supply reached");
        totalSupply += amount;
        // No overflow possible: the sum of balances == totalSupply <= 1e27.
        unchecked {
            balanceOf[to] += amount;
        }
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
            require(allowed >= value, "AQL: allowance exceeded");
            unchecked {
                allowance[from][msg.sender] = allowed - value;
            }
        }
        _transfer(from, to, value);
        return true;
    }

    function _transfer(address from, address to, uint256 value) internal {
        require(to != address(0), "AQL: transfer to zero");
        uint256 fromBalance = balanceOf[from];
        require(fromBalance >= value, "AQL: balance too low");
        unchecked {
            balanceOf[from] = fromBalance - value;
            balanceOf[to] += value;
        }
        emit Transfer(from, to, value);
    }
}
