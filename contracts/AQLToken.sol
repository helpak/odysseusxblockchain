// SPDX-License-Identifier: MIT
pragma solidity 0.8.26;

/// @title AQL — jeton natif du réseau
/// @notice Offre plafonnée à 1 milliard. Aucun premine : chaque AQL est créé
///         par le contrat de réseau (AQLNetwork) en récompense d'un travail
///         vérifié. Le déployeur ne peut faire qu'une chose, une seule fois :
///         désigner ce contrat comme émetteur. Ensuite, plus personne n'a de
///         pouvoir sur le jeton.
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

    /// @notice Désigne l'émetteur, une seule fois, de façon irréversible.
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
        // Pas de débordement possible : la somme des soldes == totalSupply <= 1e27.
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
