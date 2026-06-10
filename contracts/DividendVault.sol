// SPDX-License-Identifier: MIT
pragma solidity 0.8.26;

interface IERC20 {
    function transfer(address to, uint256 amount) external returns (bool);
    function transferFrom(address from, address to, uint256 amount) external returns (bool);
    function balanceOf(address account) external view returns (uint256);
}

/// @title DividendVault — staking ODY et partage des revenus réels
/// @notice Les revenus de l'IA (paiements par carte convertis en stablecoin)
///         sont déposés ici puis répartis instantanément :
///           - 80 % aux stakers, au prorata de leur poids ;
///           - 10 % au fondateur — adresse et pourcentage immuables, à vie ;
///           - 10 % à la trésorerie de l'équipe.
///         Plus on verrouille longtemps, plus le poids — donc la part de
///         dividendes — est élevé ("plus ils gardent, plus ça monte") :
///           tier 0 : sans verrou — poids x1.00
///           tier 1 : 90 jours   — poids x1.25
///           tier 2 : 180 jours  — poids x1.50
///           tier 3 : 365 jours  — poids x2.00
contract DividendVault {
    IERC20 public immutable ody;
    IERC20 public immutable revenueToken; // stablecoin (ex. USDC)
    address public immutable founder; // part fondateur, gravée à vie
    address public staffTreasury;
    address public owner;

    uint256 public constant FOUNDER_BPS = 1000; // 10 %
    uint256 public constant STAFF_BPS = 1000; // 10 % (stakers : 80 %)
    uint256 private constant BPS_DENOM = 10_000;
    uint256 private constant PRECISION = 1e27;

    uint256 public totalStaked;
    uint256 public totalWeight;
    uint256 public accRevenuePerWeight; // multiplié par PRECISION
    uint256 public totalRevenueDistributed;

    mapping(address => uint256) public stakedOf;
    mapping(address => uint256) public weightOf;
    mapping(address => uint8) public tierOf;
    mapping(address => uint64) public unlockAt;
    mapping(address => uint256) private _snapshot; // accRevenuePerWeight déjà comptabilisé
    mapping(address => uint256) public owedRevenue;

    uint256 private _entered = 1;

    event Staked(address indexed account, uint256 amount, uint8 tier, uint64 unlockAt);
    event Unstaked(address indexed account, uint256 amount);
    event RevenueDistributed(
        address indexed from, uint256 amount, uint256 founderCut, uint256 staffCut, uint256 stakerCut
    );
    event RevenueClaimed(address indexed account, uint256 amount);
    event StaffTreasuryChanged(address indexed newTreasury);
    event OwnershipTransferred(address indexed previousOwner, address indexed newOwner);

    modifier nonReentrant() {
        require(_entered == 1, "DV: reentrancy");
        _entered = 2;
        _;
        _entered = 1;
    }

    modifier onlyOwner() {
        require(msg.sender == owner, "DV: not owner");
        _;
    }

    /// Crédite les dividendes courus avant tout changement de poids.
    modifier settle(address account) {
        owedRevenue[account] += (weightOf[account] * (accRevenuePerWeight - _snapshot[account])) / PRECISION;
        _snapshot[account] = accRevenuePerWeight;
        _;
    }

    constructor(IERC20 ody_, IERC20 revenueToken_, address founder_, address staffTreasury_) {
        require(address(ody_) != address(0), "DV: ody is zero");
        require(address(revenueToken_) != address(0), "DV: revenue token is zero");
        require(founder_ != address(0), "DV: founder is zero");
        require(staffTreasury_ != address(0), "DV: treasury is zero");
        ody = ody_;
        revenueToken = revenueToken_;
        founder = founder_;
        staffTreasury = staffTreasury_;
        owner = msg.sender;
        emit OwnershipTransferred(address(0), msg.sender);
    }

    // --- Paliers ---

    function tierMultiplierBps(uint8 tier) public pure returns (uint256) {
        if (tier == 0) return 10_000;
        if (tier == 1) return 12_500;
        if (tier == 2) return 15_000;
        if (tier == 3) return 20_000;
        revert("DV: bad tier");
    }

    function tierLockSeconds(uint8 tier) public pure returns (uint64) {
        if (tier == 0) return 0;
        if (tier == 1) return 90 days;
        if (tier == 2) return 180 days;
        if (tier == 3) return 365 days;
        revert("DV: bad tier");
    }

    // --- Staking ---

    function stake(uint256 amount, uint8 tier) external nonReentrant settle(msg.sender) {
        require(amount > 0, "DV: zero amount");
        require(tier <= 3, "DV: bad tier");
        if (stakedOf[msg.sender] > 0) {
            require(tier >= tierOf[msg.sender], "DV: cannot lower tier");
        }
        _safeTransferFrom(ody, msg.sender, address(this), amount);

        stakedOf[msg.sender] += amount;
        totalStaked += amount;
        tierOf[msg.sender] = tier;
        uint64 newUnlock = uint64(block.timestamp) + tierLockSeconds(tier);
        if (newUnlock > unlockAt[msg.sender]) {
            unlockAt[msg.sender] = newUnlock;
        }
        _setWeight(msg.sender);
        emit Staked(msg.sender, amount, tier, unlockAt[msg.sender]);
    }

    function unstake(uint256 amount) external nonReentrant settle(msg.sender) {
        require(amount > 0 && amount <= stakedOf[msg.sender], "DV: bad amount");
        require(block.timestamp >= unlockAt[msg.sender], "DV: still locked");
        stakedOf[msg.sender] -= amount;
        totalStaked -= amount;
        if (stakedOf[msg.sender] == 0) {
            tierOf[msg.sender] = 0;
            unlockAt[msg.sender] = 0;
        }
        _setWeight(msg.sender);
        _safeTransfer(ody, msg.sender, amount);
        emit Unstaked(msg.sender, amount);
    }

    function _setWeight(address account) internal {
        uint256 newWeight = (stakedOf[account] * tierMultiplierBps(tierOf[account])) / BPS_DENOM;
        totalWeight = totalWeight - weightOf[account] + newWeight;
        weightOf[account] = newWeight;
    }

    // --- Revenus ---

    /// @notice Dépose des revenus (stablecoin) et les répartit 80/10/10.
    ///         Appelé par la trésorerie après conversion des paiements CB.
    function distributeRevenue(uint256 amount) external nonReentrant {
        require(amount > 0, "DV: zero amount");
        require(totalWeight > 0, "DV: no stakers");
        _safeTransferFrom(revenueToken, msg.sender, address(this), amount);
        uint256 founderCut = (amount * FOUNDER_BPS) / BPS_DENOM;
        uint256 staffCut = (amount * STAFF_BPS) / BPS_DENOM;
        uint256 stakerCut = amount - founderCut - staffCut;
        _safeTransfer(revenueToken, founder, founderCut);
        _safeTransfer(revenueToken, staffTreasury, staffCut);
        accRevenuePerWeight += (stakerCut * PRECISION) / totalWeight;
        totalRevenueDistributed += amount;
        emit RevenueDistributed(msg.sender, amount, founderCut, staffCut, stakerCut);
    }

    function claimRevenue() external nonReentrant settle(msg.sender) {
        uint256 amount = owedRevenue[msg.sender];
        require(amount > 0, "DV: nothing to claim");
        owedRevenue[msg.sender] = 0;
        _safeTransfer(revenueToken, msg.sender, amount);
        emit RevenueClaimed(msg.sender, amount);
    }

    /// @notice Dividendes réclamables (déjà crédités + courus depuis).
    function pendingRevenue(address account) external view returns (uint256) {
        return owedRevenue[account] + (weightOf[account] * (accRevenuePerWeight - _snapshot[account])) / PRECISION;
    }

    // --- Administration ---

    function setStaffTreasury(address newTreasury) external onlyOwner {
        require(newTreasury != address(0), "DV: treasury is zero");
        staffTreasury = newTreasury;
        emit StaffTreasuryChanged(newTreasury);
    }

    function transferOwnership(address newOwner) external onlyOwner {
        require(newOwner != address(0), "DV: new owner is zero");
        emit OwnershipTransferred(owner, newOwner);
        owner = newOwner;
    }

    // --- Transferts tolérants aux tokens sans valeur de retour (type USDT) ---

    function _safeTransfer(IERC20 token_, address to, uint256 value) private {
        (bool ok, bytes memory data) =
            address(token_).call(abi.encodeWithSelector(token_.transfer.selector, to, value));
        require(ok && (data.length == 0 || abi.decode(data, (bool))), "DV: transfer failed");
    }

    function _safeTransferFrom(IERC20 token_, address from, address to, uint256 value) private {
        (bool ok, bytes memory data) =
            address(token_).call(abi.encodeWithSelector(token_.transferFrom.selector, from, to, value));
        require(ok && (data.length == 0 || abi.decode(data, (bool))), "DV: transferFrom failed");
    }
}
