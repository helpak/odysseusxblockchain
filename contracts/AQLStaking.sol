// SPDX-License-Identifier: MIT
pragma solidity 0.8.26;

import "./SafeToken.sol";

/// @title AQLStaking — AQL holders receive 33% of payments
/// @notice Every user payment (in USDT) sends 33% here. This revenue
///         is not paid out all at once: it streams second by
///         second over STREAM_DURATION (7 days). As a result, staking right
///         before a large payment and withdrawing right after earns
///         almost nothing — each staker's share is proportional to the time
///         actually spent staked, multiplied by their weight.
///
///         The weight depends on the chosen lock ("the longer you hold, the more you earn"):
///           tier 0: no lock    — ×1.00
///           tier 1: 90 days    — ×1.25
///           tier 2: 180 days   — ×1.50
///           tier 3: 365 days   — ×2.00
///
///         No administrator. The deployer designates, once only, the
///         AQLNetwork contract, the only one allowed to announce new revenue.
contract AQLStaking {
    using SafeToken for IERC20Min;

    IERC20Min public immutable aql;
    IERC20Min public immutable usdt;
    address public network;
    address private immutable _deployer;

    uint256 public constant STREAM_DURATION = 7 days;
    uint256 private constant BPS = 10_000;
    // rewardRate is expressed in USDT * RATE_SCALE per second; the accumulator
    // in USDT * RATE_SCALE * ACC_SCALE per unit of weight.
    uint256 private constant RATE_SCALE = 1e18;
    uint256 private constant ACC_SCALE = 1e18;

    // --- staking ---
    uint256 public totalStaked;
    uint256 public totalWeight;
    mapping(address => uint256) public stakedOf;
    mapping(address => uint256) public weightOf;
    mapping(address => uint8) public tierOf;
    mapping(address => uint64) public unlockAt;

    // --- revenue streaming ---
    uint256 public rewardRate;
    uint256 public periodFinish;
    uint256 public lastUpdateTime;
    uint256 public accRewardPerWeight;
    /// Revenue streamed while no weight was staked: put back into
    /// circulation at the next announcement instead of being lost.
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

    /// @notice Designates AQLNetwork, once and irreversibly.
    function initNetwork(address network_) external {
        require(msg.sender == _deployer, "AQLS: not deployer");
        require(network == address(0), "AQLS: network already set");
        require(network_.code.length > 0, "AQLS: network not a contract");
        network = network_;
        emit NetworkSet(network_);
    }

    // ------------------------------------------------------------ tiers

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

    // ------------------------------------------------------------ accounting

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

    // ------------------------------------------------------------ revenue

    /// @notice Takes in all USDT that arrived since the last announcement and spreads
    ///         it over the next 7 days, together with the remainder not yet streamed.
    ///         The amount received is measured from the contract's actual balance:
    ///         no declared amount is taken on trust.
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

    /// @notice USDT claimable now by `account` (credited + streamed since).
    function pendingRevenue(address account) external view returns (uint256) {
        uint256 acc = accRewardPerWeight;
        uint256 applicable = _lastApplicable();
        if (applicable > lastUpdateTime && totalWeight > 0) {
            acc += ((applicable - lastUpdateTime) * rewardRate * ACC_SCALE) / totalWeight;
        }
        return owed[account] + (weightOf[account] * (acc - _accPaid[account])) / (RATE_SCALE * ACC_SCALE);
    }
}
