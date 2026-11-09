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

/// @title AQLNetwork — émission, paiements et récompenses du réseau AQL
/// @notice Trois rôles, sans aucun administrateur :
///
///   1. ÉMISSION (comme Bitcoin) — 1 époque = 1 jour à partir de `genesis`.
///      Chaque époque peut créer au plus epochReward(e) AQL, divisé par 2
///      toutes les 730 époques (~2 ans). Une époque ne peut être réglée
///      qu'une fois terminée : le calendrier est garanti par l'horloge de la
///      chaîne, pas par un opérateur. L'émission non attribuée n'est jamais
///      créée.
///
///   2. PAIEMENTS — un utilisateur paie en USDT via pay(). Le montant
///      réellement reçu est réparti à la seconde : 67 % au pool des mineurs,
///      33 % aux stakers d'AQL (contrat AQLStaking).
///
///   3. RÉCOMPENSES — pour chaque époque terminée, les oracles publient la
///      racine merkle des gains vérifiés (AQL émis + USDT du pool mineurs).
///      Il faut `threshold` oracles d'accord sur exactement les mêmes
///      valeurs. Chaque époque est plafonnée : impossible de réclamer plus
///      que ce que l'époque a déclaré, impossible de déclarer plus que la
///      récompense d'époque ou que le pool mineurs disponible.
///
///   Les oracles peuvent remplacer l'un des leurs, au même seuil de vote
///   (clé perdue ou compromise). Rien d'autre n'est modifiable.
///
///   Merkle en sha256 (et non keccak256) : le coordinateur reproduit arbres et
///   preuves en Python standard (hashlib), sans dépendance.
contract AQLNetwork {
    using SafeToken for IERC20Min;

    IAQLToken public immutable aql;
    IERC20Min public immutable usdt;
    address public immutable staking;
    uint256 public immutable genesis;
    uint256 public immutable threshold;

    uint256 public constant EPOCH_SECONDS = 1 days;
    uint256 public constant HALVING_INTERVAL = 730; // époques (~2 ans)
    /// 1e27 / 1460, arrondi par défaut : l'émission totale converge vers
    /// 1 milliard d'AQL sans jamais l'atteindre.
    uint256 public constant INITIAL_EPOCH_REWARD = 684931506849315068493150;
    uint256 public constant MINER_BPS = 6_700; // 67 % mineurs, 33 % stakers
    uint256 private constant BPS = 10_000;

    // --- oracles ---
    mapping(address => bool) public isOracle;
    uint256 public oracleCount;
    /// Incrémenté à chaque remplacement d'oracle : invalide tous les votes en cours.
    uint256 public oracleNonce;
    mapping(bytes32 => uint256) public votes;
    mapping(bytes32 => mapping(address => bool)) public hasVoted;

    // --- époques ---
    mapping(uint256 => bytes32) public epochRoot;
    mapping(uint256 => uint256) public aqlRemaining;
    mapping(uint256 => uint256) public usdtRemaining;
    mapping(uint256 => mapping(uint256 => uint256)) private _claimedBitMap;

    // --- revenus ---
    /// USDT destiné aux mineurs, reçu mais pas encore attribué à une époque.
    uint256 public minerPool;
    /// Total USDT reçu des utilisateurs depuis le lancement.
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
        // Majorité stricte : deux groupes disjoints d'oracles ne peuvent jamais
        // atteindre le seuil chacun de leur côté.
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

    // ------------------------------------------------------------ émission

    /// @notice Nombre d'époques entièrement écoulées : seules elles sont réglables.
    function finishedEpochs() public view returns (uint256) {
        if (block.timestamp < genesis) return 0;
        return (block.timestamp - genesis) / EPOCH_SECONDS;
    }

    /// @notice AQL maximum créable pour une époque (halving tous les 730 jours).
    function epochReward(uint256 epochId) public pure returns (uint256) {
        uint256 halvings = epochId / HALVING_INTERVAL;
        if (halvings >= 64) return 0;
        return INITIAL_EPOCH_REWARD >> halvings;
    }

    // ------------------------------------------------------------ paiements

    /// @notice Paiement d'un utilisateur. `accountRef` identifie le compte IA à
    ///         créditer (hash d'identifiant), lu par le service via l'événement Paid.
    function pay(uint256 amount, bytes32 accountRef) external nonReentrant {
        require(amount > 0, "AQLN: zero amount");
        uint256 before = usdt.balanceOf(address(this));
        usdt.safeTransferFrom(msg.sender, address(this), amount);
        // Montant réellement reçu : robuste à un éventuel frais de transfert USDT.
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

    // ------------------------------------------------------------ époques

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

    /// @notice Réclame les gains d'une époque. N'importe qui peut payer le gas :
    ///         les fonds vont toujours à `account`.
    /// Feuille : sha256(abi.encodePacked(epochId, index, account, aqlAmount, usdtAmount)).
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

    /// @notice Réclame plusieurs époques en une seule transaction (frais réduits
    ///         sur Ethereum) : un seul transfert AQL et un seul transfert USDT.
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

    /// @notice Remplace un oracle (clé perdue/compromise), au même seuil de vote.
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
