// SPDX-License-Identifier: MIT
pragma solidity 0.8.26;

import "./SafeToken.sol";

interface IAQLToken {
    function mint(address to, uint256 amount) external;
    function transfer(address to, uint256 amount) external returns (bool);
}

interface IAQLStaking {
    function notifyRevenue() external;
}

/// @title AQLNetwork — emission, payments and rewards of the AQL network
/// @notice Three roles, with no administrator at all:
///
///   1. EMISSION (like Bitcoin) — 1 epoch = 1 day starting from `genesis`.
///      Each epoch can create at most epochReward(e) AQL, halved every
///      730 epochs (~2 years). An epoch can only be settled once it has
///      ended: the schedule is enforced by the chain's clock, not by an
///      operator. Emission that is not allocated to anyone is never
///      created.
///
///   2. PAYMENTS — a user pays in USDT via pay(). The amount actually
///      received is split immediately: 67% to the miner pool,
///      33% to AQL stakers (AQLStaking contract).
///
///   3. REWARDS — for each finished epoch, the oracles publish the merkle
///      root of verified earnings (AQL emitted + USDT from the miner pool).
///      `threshold` oracles must agree on exactly the same values.
///      Each epoch is capped: it is impossible to claim more than
///      the epoch declared, and impossible to declare more than the
///      epoch reward or the available miner pool.
///
///   The oracles can replace one of their own, at the same voting threshold
///   (lost or compromised key). Nothing else can be changed.
///
///   Merkle trees use sha256 (not keccak256): the coordinator rebuilds trees and
///   proofs in standard Python (hashlib), with no dependencies.
contract AQLNetwork {
    using SafeToken for IERC20Min;

    IAQLToken public immutable aql;
    IERC20Min public immutable usdt;
    address public immutable staking;
    uint256 public immutable genesis;
    uint256 public immutable threshold;

    uint256 public constant EPOCH_SECONDS = 1 days;
    uint256 public constant HALVING_INTERVAL = 730; // epochs (~2 years)
    /// 1e27 / 1460, rounded down: total emission converges towards
    /// 1 billion AQL without ever reaching it.
    uint256 public constant INITIAL_EPOCH_REWARD = 684931506849315068493150;
    uint256 public constant MINER_BPS = 6_700; // 67% miners, 33% stakers
    uint256 private constant BPS = 10_000;

    // --- oracles ---
    mapping(address => bool) public isOracle;
    uint256 public oracleCount;
    /// Incremented on every oracle replacement: invalidates all pending votes.
    uint256 public oracleNonce;
    mapping(bytes32 => uint256) public votes;
    mapping(bytes32 => mapping(address => bool)) public hasVoted;

    // --- epochs ---
    mapping(uint256 => bytes32) public epochRoot;
    mapping(uint256 => uint256) public aqlRemaining;
    mapping(uint256 => uint256) public usdtRemaining;
    mapping(uint256 => mapping(uint256 => uint256)) private _claimedBitMap;

    // --- revenue ---
    /// USDT intended for miners, received but not yet allocated to an epoch.
    uint256 public minerPool;
    /// Total USDT received from users since launch.
    uint256 public totalPaid;

    uint256 private _entered = 1;

    event Paid(
        address indexed payer, bytes32 indexed accountRef, uint256 received, uint256 minerCut, uint256 holderCut
    );
    event EpochVote(
        uint256 indexed epochId, address indexed oracle, bytes32 root, uint256 aqlTotal, uint256 usdtTotal, uint256 votes
    );
    event EpochFinalized(uint256 indexed epochId, bytes32 root, uint256 aqlTotal, uint256 usdtTotal);
    event Claimed(uint256 indexed epochId, uint256 index, address indexed account, uint256 aqlAmount, uint256 usdtAmount);
    event OracleVote(address indexed oldOracle, address indexed newOracle, address indexed voter, uint256 votes);
    event OracleReplaced(address indexed oldOracle, address indexed newOracle);

    modifier nonReentrant() {
        require(_entered == 1, "AQLN: reentrancy");
        _entered = 2;
        _;
        _entered = 1;
    }

    modifier onlyOracle() {
        require(isOracle[msg.sender], "AQLN: not oracle");
        _;
    }

    constructor(
        IAQLToken aql_,
        IERC20Min usdt_,
        address staking_,
        uint256 genesis_,
        address[] memory oracles_,
        uint256 threshold_
    ) {
        require(address(aql_).code.length > 0, "AQLN: aql not a contract");
        require(address(usdt_).code.length > 0, "AQLN: usdt not a contract");
        require(staking_.code.length > 0, "AQLN: staking not a contract");
        require(threshold_ > 0 && threshold_ <= oracles_.length, "AQLN: bad threshold");
        // Strict majority: two disjoint groups of oracles can never each
        // reach the threshold on their own.
        require(threshold_ * 2 > oracles_.length, "AQLN: threshold must be a majority");
        for (uint256 i = 0; i < oracles_.length; i++) {
            address o = oracles_[i];
            require(o != address(0), "AQLN: oracle is zero");
            require(!isOracle[o], "AQLN: duplicate oracle");
            isOracle[o] = true;
        }
        aql = aql_;
        usdt = usdt_;
        staking = staking_;
        genesis = genesis_;
        threshold = threshold_;
        oracleCount = oracles_.length;
    }

    // ------------------------------------------------------------ emission

    /// @notice Number of fully elapsed epochs: only these can be settled.
    function finishedEpochs() public view returns (uint256) {
        if (block.timestamp < genesis) return 0;
        return (block.timestamp - genesis) / EPOCH_SECONDS;
    }

    /// @notice Maximum AQL that can be created for an epoch (halving every 730 days).
    function epochReward(uint256 epochId) public pure returns (uint256) {
        uint256 halvings = epochId / HALVING_INTERVAL;
        if (halvings >= 64) return 0;
        return INITIAL_EPOCH_REWARD >> halvings;
    }

    // ------------------------------------------------------------ payments

    /// @notice Payment from a user. `accountRef` identifies the AI account to
    ///         credit (identifier hash), read by the service from the Paid event.
    function pay(uint256 amount, bytes32 accountRef) external nonReentrant {
        require(amount > 0, "AQLN: zero amount");
        uint256 before = usdt.balanceOf(address(this));
        usdt.safeTransferFrom(msg.sender, address(this), amount);
        // Amount actually received: robust to a possible USDT transfer fee.
        uint256 received = usdt.balanceOf(address(this)) - before;
        require(received > 0, "AQLN: nothing received");

        uint256 minerCut = (received * MINER_BPS) / BPS;
        uint256 holderCut = received - minerCut;
        minerPool += minerCut;
        totalPaid += received;

        usdt.safeTransfer(staking, holderCut);
        IAQLStaking(staking).notifyRevenue();
        emit Paid(msg.sender, accountRef, received, minerCut, holderCut);
    }

    // ------------------------------------------------------------ epochs

    function proposeEpoch(uint256 epochId, bytes32 root, uint256 aqlTotal, uint256 usdtTotal)
        external
        onlyOracle
        nonReentrant
    {
        require(epochId < finishedEpochs(), "AQLN: epoch not finished");
        require(epochRoot[epochId] == bytes32(0), "AQLN: epoch already finalized");
        require(root != bytes32(0), "AQLN: empty root");
        require(aqlTotal <= epochReward(epochId), "AQLN: above epoch reward");

        bytes32 key = keccak256(abi.encode("epoch", oracleNonce, epochId, root, aqlTotal, usdtTotal));
        require(!hasVoted[key][msg.sender], "AQLN: already voted");
        hasVoted[key][msg.sender] = true;
        uint256 v = ++votes[key];
        emit EpochVote(epochId, msg.sender, root, aqlTotal, usdtTotal, v);

        if (v >= threshold) {
            require(usdtTotal <= minerPool, "AQLN: above miner pool");
            minerPool -= usdtTotal;
            epochRoot[epochId] = root;
            aqlRemaining[epochId] = aqlTotal;
            usdtRemaining[epochId] = usdtTotal;
            if (aqlTotal > 0) {
                aql.mint(address(this), aqlTotal);
            }
            emit EpochFinalized(epochId, root, aqlTotal, usdtTotal);
        }
    }

    function isClaimed(uint256 epochId, uint256 index) public view returns (bool) {
        uint256 word = _claimedBitMap[epochId][index / 256];
        return ((word >> (index % 256)) & 1) == 1;
    }

    struct ClaimItem {
        uint256 epochId;
        uint256 index;
        uint256 aqlAmount;
        uint256 usdtAmount;
        bytes32[] proof;
    }

    /// @notice Claims the earnings of an epoch. Anyone can pay the gas:
    ///         the funds always go to `account`.
    /// Leaf: sha256(abi.encodePacked(epochId, index, account, aqlAmount, usdtAmount)).
    function claim(
        uint256 epochId,
        uint256 index,
        address account,
        uint256 aqlAmount,
        uint256 usdtAmount,
        bytes32[] calldata proof
    ) external nonReentrant {
        _consume(epochId, index, account, aqlAmount, usdtAmount, proof);
        _payout(account, aqlAmount, usdtAmount);
    }

    /// @notice Claims several epochs in a single transaction (lower fees
    ///         on Ethereum): a single AQL transfer and a single USDT transfer.
    function claimMany(address account, ClaimItem[] calldata items) external nonReentrant {
        uint256 aqlTotal;
        uint256 usdtTotal;
        for (uint256 i = 0; i < items.length; i++) {
            ClaimItem calldata it = items[i];
            _consume(it.epochId, it.index, account, it.aqlAmount, it.usdtAmount, it.proof);
            aqlTotal += it.aqlAmount;
            usdtTotal += it.usdtAmount;
        }
        _payout(account, aqlTotal, usdtTotal);
    }

    function _consume(
        uint256 epochId,
        uint256 index,
        address account,
        uint256 aqlAmount,
        uint256 usdtAmount,
        bytes32[] calldata proof
    ) private {
        bytes32 root = epochRoot[epochId];
        require(root != bytes32(0), "AQLN: unknown epoch");
        require(!isClaimed(epochId, index), "AQLN: already claimed");
        bytes32 leaf = sha256(abi.encodePacked(epochId, index, account, aqlAmount, usdtAmount));
        require(_verify(proof, root, leaf), "AQLN: invalid proof");
        require(aqlAmount <= aqlRemaining[epochId], "AQLN: epoch AQL cap");
        require(usdtAmount <= usdtRemaining[epochId], "AQLN: epoch USDT cap");

        _claimedBitMap[epochId][index / 256] |= (uint256(1) << (index % 256));
        aqlRemaining[epochId] -= aqlAmount;
        usdtRemaining[epochId] -= usdtAmount;
        emit Claimed(epochId, index, account, aqlAmount, usdtAmount);
    }

    function _payout(address account, uint256 aqlAmount, uint256 usdtAmount) private {
        if (aqlAmount > 0) {
            require(aql.transfer(account, aqlAmount), "AQLN: AQL transfer failed");
        }
        if (usdtAmount > 0) {
            usdt.safeTransfer(account, usdtAmount);
        }
    }

    function _verify(bytes32[] calldata proof, bytes32 root, bytes32 leaf) private pure returns (bool) {
        bytes32 computed = leaf;
        for (uint256 i = 0; i < proof.length; i++) {
            bytes32 p = proof[i];
            computed = computed <= p
                ? sha256(abi.encodePacked(computed, p))
                : sha256(abi.encodePacked(p, computed));
        }
        return computed == root;
    }

    // ------------------------------------------------------------ oracles

    /// @notice Replaces an oracle (lost/compromised key), at the same voting threshold.
    function voteReplaceOracle(address oldOracle, address newOracle) external onlyOracle {
        require(isOracle[oldOracle], "AQLN: not an oracle");
        require(newOracle != address(0) && !isOracle[newOracle], "AQLN: bad new oracle");
        bytes32 key = keccak256(abi.encode("replace", oracleNonce, oldOracle, newOracle));
        require(!hasVoted[key][msg.sender], "AQLN: already voted");
        hasVoted[key][msg.sender] = true;
        uint256 v = ++votes[key];
        emit OracleVote(oldOracle, newOracle, msg.sender, v);
        if (v >= threshold) {
            isOracle[oldOracle] = false;
            isOracle[newOracle] = true;
            oracleNonce++;
            emit OracleReplaced(oldOracle, newOracle);
        }
    }
}
