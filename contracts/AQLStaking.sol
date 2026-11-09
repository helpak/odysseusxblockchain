// SPDX-License-Identifier: MIT
pragma solidity 0.8.26;

import "./SafeToken.sol";

/// @title AQLStaking — les détenteurs d'AQL reçoivent 33 % des paiements
/// @notice Chaque paiement d'un utilisateur (en USDT) envoie 33 % ici. Ces
///         revenus ne sont pas versés d'un coup : ils s'écoulent seconde par
///         seconde sur STREAM_DURATION (7 jours). Conséquence : staker juste
///         avant un gros paiement puis retirer juste après ne rapporte
///         presque rien — la part de chacun est proportionnelle au temps
///         réellement passé staké, multiplié par son poids.
///
///         Le poids dépend du verrouillage choisi ("plus on garde, plus ça monte") :
///           palier 0 : sans verrou — ×1,00
///           palier 1 : 90 jours   — ×1,25
///           palier 2 : 180 jours  — ×1,50
///           palier 3 : 365 jours  — ×2,00
///
///         Aucun administrateur. Le déployeur désigne une seule fois le contrat
///         AQLNetwork, seul autorisé à annoncer de nouveaux revenus.
contract AQLStaking {
    using SafeToken for IERC20Min;

    IERC20Min public immutable aql;
    IERC20Min public immutable usdt;
    address public network;
    address private immutable _deployer;

    uint256 public constant STREAM_DURATION = 7 days;
    uint256 private constant BPS = 10_000;
    // rewardRate est exprimé en USDT * RATE_SCALE par seconde ; l'accumulateur
    // en USDT * RATE_SCALE * ACC_SCALE par unité de poids.
    uint256 private constant RATE_SCALE = 1e18;
    uint256 private constant ACC_SCALE = 1e18;

    // --- staking ---
    uint256 public totalStaked;
    uint256 public totalWeight;
    mapping(address => uint256) public stakedOf;
    mapping(address => uint256) public weightOf;
    mapping(address => uint8) public tierOf;
    mapping(address => uint64) public unlockAt;

    // --- écoulement des revenus ---
    uint256 public rewardRate;
    uint256 public periodFinish;
    uint256 public lastUpdateTime;
    uint256 public accRewardPerWeight;
    /// Revenus écoulés pendant qu'aucun poids n'était staké : remis en
    /// circulation à l'annonce suivante au lieu d'être perdus.
    uint256 public queuedScaled;
    mapping(address => uint256) private _accPaid;
    mapping(address => uint256) public owed;

    uint256 public totalReceived;
    uint256 public totalClaimed;

    uint256 private _entered = 1;

    event NetworkSet(address indexed network);
    event Staked(address indexed account, uint256 amount, uint8 tier, uint64 unlockAt);
    event Unstaked(address indexed account, uint256 amount);
    event RevenueNotified(uint256 received, uint256 rewardRate, uint256 periodFinish);
    event RevenueClaimed(address indexed account, uint256 amount);

    modifier nonReentrant() {
        require(_entered == 1, "AQLS: reentrancy");
        _entered = 2;
        _;
        _entered = 1;
    }

    constructor(IERC20Min aql_, IERC20Min usdt_) {
        require(address(aql_).code.length > 0, "AQLS: aql not a contract");
        require(address(usdt_).code.length > 0, "AQLS: usdt not a contract");
        aql = aql_;
        usdt = usdt_;
        _deployer = msg.sender;
    }

    /// @notice Désigne AQLNetwork, une seule fois, de façon irréversible.
    function initNetwork(address network_) external {
        require(msg.sender == _deployer, "AQLS: not deployer");
        require(network == address(0), "AQLS: network already set");
        require(network_.code.length > 0, "AQLS: network not a contract");
        network = network_;
        emit NetworkSet(network_);
    }

    // ------------------------------------------------------------ paliers

    function tierMultiplierBps(uint8 tier) public pure returns (uint256) {
        if (tier == 0) return 10_000;
        if (tier == 1) return 12_500;
        if (tier == 2) return 15_000;
        if (tier == 3) return 20_000;
        revert("AQLS: bad tier");
    }

    function tierLockSeconds(uint8 tier) public pure returns (uint64) {
        if (tier == 0) return 0;
        if (tier == 1) return 90 days;
        if (tier == 2) return 180 days;
        if (tier == 3) return 365 days;
        revert("AQLS: bad tier");
    }

    // ------------------------------------------------------------ comptabilité

    function _lastApplicable() private view returns (uint256) {
        return block.timestamp < periodFinish ? block.timestamp : periodFinish;
    }

    function _update(address account) private {
        uint256 applicable = _lastApplicable();
        if (applicable > lastUpdateTime) {
            uint256 streamed = (applicable - lastUpdateTime) * rewardRate;
            if (totalWeight == 0) {
                queuedScaled += streamed;
            } else {
                accRewardPerWeight += (streamed * ACC_SCALE) / totalWeight;
            }
            lastUpdateTime = applicable;
        }
        if (account != address(0)) {
            owed[account] +=
                (weightOf[account] * (accRewardPerWeight - _accPaid[account])) / (RATE_SCALE * ACC_SCALE);
            _accPaid[account] = accRewardPerWeight;
        }
    }

    function _setWeight(address account) private {
        uint256 newWeight = (stakedOf[account] * tierMultiplierBps(tierOf[account])) / BPS;
        totalWeight = totalWeight - weightOf[account] + newWeight;
        weightOf[account] = newWeight;
    }

    // ------------------------------------------------------------ staking

    function stake(uint256 amount, uint8 tier) external nonReentrant {
        require(amount > 0, "AQLS: zero amount");
        require(tier <= 3, "AQLS: bad tier");
        if (stakedOf[msg.sender] > 0) {
            require(tier >= tierOf[msg.sender], "AQLS: cannot lower tier");
        }
        _update(msg.sender);
        aql.safeTransferFrom(msg.sender, address(this), amount);

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

    function unstake(uint256 amount) external nonReentrant {
        require(amount > 0 && amount <= stakedOf[msg.sender], "AQLS: bad amount");
        require(block.timestamp >= unlockAt[msg.sender], "AQLS: still locked");
        _update(msg.sender);
        stakedOf[msg.sender] -= amount;
        totalStaked -= amount;
        if (stakedOf[msg.sender] == 0) {
            tierOf[msg.sender] = 0;
            unlockAt[msg.sender] = 0;
        }
        _setWeight(msg.sender);
        aql.safeTransfer(msg.sender, amount);
        emit Unstaked(msg.sender, amount);
    }

    // ------------------------------------------------------------ revenus

    /// @notice Intègre tout USDT arrivé depuis la dernière annonce et l'étale
    ///         sur les 7 prochains jours, avec le reliquat non encore écoulé.
    ///         La quantité reçue est mesurée sur le solde réel du contrat :
    ///         aucun montant déclaré n'est cru sur parole.
    function notifyRevenue() external nonReentrant {
        require(msg.sender == network, "AQLS: not network");
        _update(address(0));

        uint256 balance = usdt.balanceOf(address(this));
        uint256 accounted = totalReceived - totalClaimed;
        uint256 received = balance > accounted ? balance - accounted : 0;
        if (received == 0 && queuedScaled == 0) return;
        totalReceived += received;

        uint256 leftover = block.timestamp < periodFinish ? (periodFinish - block.timestamp) * rewardRate : 0;
        uint256 toStream = received * RATE_SCALE + leftover + queuedScaled;
        queuedScaled = 0;
        rewardRate = toStream / STREAM_DURATION;
        lastUpdateTime = block.timestamp;
        periodFinish = block.timestamp + STREAM_DURATION;
        emit RevenueNotified(received, rewardRate, periodFinish);
    }

    function claimRevenue() external nonReentrant {
        _update(msg.sender);
        uint256 amount = owed[msg.sender];
        require(amount > 0, "AQLS: nothing to claim");
        owed[msg.sender] = 0;
        totalClaimed += amount;
        usdt.safeTransfer(msg.sender, amount);
        emit RevenueClaimed(msg.sender, amount);
    }

    /// @notice USDT réclamable maintenant par `account` (crédité + écoulé depuis).
    function pendingRevenue(address account) external view returns (uint256) {
        uint256 acc = accRewardPerWeight;
        uint256 applicable = _lastApplicable();
        if (applicable > lastUpdateTime && totalWeight > 0) {
            acc += ((applicable - lastUpdateTime) * rewardRate * ACC_SCALE) / totalWeight;
        }
        return owed[account] + (weightOf[account] * (acc - _accPaid[account])) / (RATE_SCALE * ACC_SCALE);
    }
}
