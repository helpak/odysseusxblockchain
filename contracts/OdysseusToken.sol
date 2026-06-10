// SPDX-License-Identifier: MIT
pragma solidity 0.8.26;

/// @title Odysseus Network Token (ODY)
/// @notice Jeton natif du réseau Odysseus. Offre maximale fixe de 1 milliard.
///         10 % sont émis au fondateur au déploiement ; les 90 % restants ne
///         peuvent être créés que par le `minter` (le RewardsDistributor, qui
///         applique l'émission de minage avec halving). Aucune autre création
///         de jetons n'est possible : le plafond est gravé dans le contrat.
contract OdysseusToken {
    string public constant name = "Odysseus Network";
    string public constant symbol = "ODY";
    uint8 public constant decimals = 18;

    uint256 public constant MAX_SUPPLY = 1_000_000_000e18; // 1 milliard d'ODY
    uint256 public constant FOUNDER_ALLOCATION = MAX_SUPPLY / 10; // 10 %

    uint256 public totalSupply;
    address public owner;
    address public minter; // RewardsDistributor
    bool public minterLocked; // une fois verrouillé, le minter ne change plus jamais

    mapping(address => uint256) public balanceOf;
    mapping(address => mapping(address => uint256)) public allowance;

    event Transfer(address indexed from, address indexed to, uint256 value);
    event Approval(address indexed holder, address indexed spender, uint256 value);
    event MinterChanged(address indexed newMinter);
    event MinterLocked();
    event OwnershipTransferred(address indexed previousOwner, address indexed newOwner);

    modifier onlyOwner() {
        require(msg.sender == owner, "ODY: not owner");
        _;
    }

    /// @param founder Adresse du fondateur : reçoit les 10 % initiaux.
    ///        Le déployeur garde l'ownership le temps de câbler le minter,
    ///        puis le transfère (voir scripts/deploy.js).
    constructor(address founder) {
        require(founder != address(0), "ODY: founder is zero");
        owner = msg.sender;
        emit OwnershipTransferred(address(0), msg.sender);
        _mint(founder, FOUNDER_ALLOCATION);
    }

    // --- Administration ---

    function setMinter(address newMinter) external onlyOwner {
        require(!minterLocked, "ODY: minter locked");
        minter = newMinter;
        emit MinterChanged(newMinter);
    }

    /// @notice Verrouille définitivement le minter. Geste de confiance public :
    ///         après cet appel, plus personne (fondateur inclus) ne peut brancher
    ///         un autre contrat d'émission.
    function lockMinter() external onlyOwner {
        require(minter != address(0), "ODY: minter unset");
        minterLocked = true;
        emit MinterLocked();
    }

    function transferOwnership(address newOwner) external onlyOwner {
        require(newOwner != address(0), "ODY: new owner is zero");
        emit OwnershipTransferred(owner, newOwner);
        owner = newOwner;
    }

    // --- Émission (RewardsDistributor uniquement) ---

    function mint(address to, uint256 amount) external {
        require(msg.sender == minter, "ODY: not minter");
        _mint(to, amount);
    }

    function _mint(address to, uint256 amount) internal {
        require(to != address(0), "ODY: mint to zero");
        require(totalSupply + amount <= MAX_SUPPLY, "ODY: max supply reached");
        totalSupply += amount;
        // Pas de débordement possible : la somme des soldes == totalSupply <= 1e27.
        unchecked {
            balanceOf[to] += amount;
        }
        emit Transfer(address(0), to, amount);
    }

    // --- ERC-20 ---

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
            require(allowed >= value, "ODY: allowance exceeded");
            unchecked {
                allowance[from][msg.sender] = allowed - value;
            }
        }
        _transfer(from, to, value);
        return true;
    }

    function _transfer(address from, address to, uint256 value) internal {
        require(to != address(0), "ODY: transfer to zero");
        uint256 fromBalance = balanceOf[from];
        require(fromBalance >= value, "ODY: balance too low");
        unchecked {
            balanceOf[from] = fromBalance - value;
            balanceOf[to] += value;
        }
        emit Transfer(from, to, value);
    }
}
