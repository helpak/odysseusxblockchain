// SPDX-License-Identifier: MIT
pragma solidity 0.8.26;

interface IOdysseusToken {
    function mint(address to, uint256 amount) external;
    function transfer(address to, uint256 amount) external returns (bool);
}

/// @title RewardsDistributor — émission de minage avec halving
/// @notice À chaque époque (1 jour), le coordinateur (l'oracle) publie la
///         racine merkle des récompenses gagnées par les mineurs — GPU
///         (améliorateurs + voteurs) et stockage. Le contrat émet alors la
///         récompense d'époque, qui diminue de moitié toutes les
///         HALVING_INTERVAL époques, comme Bitcoin. Chaque mineur réclame
///         ensuite sa part avec une preuve merkle.
///
///         Les feuilles et nœuds merkle utilisent sha256 (et non keccak256)
///         pour que le coordinateur puisse générer arbres et preuves en
///         Python standard (hashlib), sans aucune dépendance externe.
contract RewardsDistributor {
    IOdysseusToken public immutable token;

    /// Récompense de l'époque 0 : 616 438 ODY/jour. Avec un halving tous les
    /// 730 jours (~2 ans), l'émission totale converge vers ~900 M d'ODY :
    /// exactement les 90 % de l'offre non attribués au fondateur.
    uint256 public constant INITIAL_EPOCH_REWARD = 616_438e18;
    uint256 public constant HALVING_INTERVAL = 730; // époques (jours)

    address public owner;
    address public oracle; // clé du coordinateur : publie les racines merkle

    mapping(uint256 => bytes32) public epochRoot;
    mapping(uint256 => uint256) public epochMinted;
    // epochId => index de mot => bitmap "déjà réclamé"
    mapping(uint256 => mapping(uint256 => uint256)) private _claimedBitMap;

    event OracleChanged(address indexed newOracle);
    event OwnershipTransferred(address indexed previousOwner, address indexed newOwner);
    event EpochSubmitted(uint256 indexed epochId, bytes32 merkleRoot, uint256 minted);
    event Claimed(uint256 indexed epochId, uint256 index, address indexed account, uint256 amount);

    modifier onlyOwner() {
        require(msg.sender == owner, "RD: not owner");
        _;
    }

    constructor(IOdysseusToken token_, address oracle_) {
        require(address(token_) != address(0), "RD: token is zero");
        require(oracle_ != address(0), "RD: oracle is zero");
        token = token_;
        oracle = oracle_;
        owner = msg.sender;
        emit OwnershipTransferred(address(0), msg.sender);
        emit OracleChanged(oracle_);
    }

    function setOracle(address newOracle) external onlyOwner {
        require(newOracle != address(0), "RD: oracle is zero");
        oracle = newOracle;
        emit OracleChanged(newOracle);
    }

    function transferOwnership(address newOwner) external onlyOwner {
        require(newOwner != address(0), "RD: new owner is zero");
        emit OwnershipTransferred(owner, newOwner);
        owner = newOwner;
    }

    /// @notice Récompense totale émise pour une époque donnée (halving).
    function epochReward(uint256 epochId) public pure returns (uint256) {
        uint256 halvings = epochId / HALVING_INTERVAL;
        if (halvings >= 64) return 0;
        return INITIAL_EPOCH_REWARD >> halvings;
    }

    /// @notice Publie la racine merkle d'une époque et émet sa récompense.
    function submitEpoch(uint256 epochId, bytes32 merkleRoot) external {
        require(msg.sender == oracle, "RD: not oracle");
        require(merkleRoot != bytes32(0), "RD: empty root");
        require(epochRoot[epochId] == bytes32(0), "RD: epoch already submitted");
        epochRoot[epochId] = merkleRoot;
        uint256 reward = epochReward(epochId);
        if (reward > 0) {
            token.mint(address(this), reward);
        }
        epochMinted[epochId] = reward;
        emit EpochSubmitted(epochId, merkleRoot, reward);
    }

    function isClaimed(uint256 epochId, uint256 index) public view returns (bool) {
        uint256 word = _claimedBitMap[epochId][index / 256];
        return ((word >> (index % 256)) & 1) == 1;
    }

    /// @notice Réclame la récompense de minage d'une époque.
    /// Feuille : sha256(abi.encodePacked(epochId, index, account, amount)).
    function claim(
        uint256 epochId,
        uint256 index,
        address account,
        uint256 amount,
        bytes32[] calldata proof
    ) external {
        require(epochRoot[epochId] != bytes32(0), "RD: unknown epoch");
        require(!isClaimed(epochId, index), "RD: already claimed");
        bytes32 leaf = sha256(abi.encodePacked(epochId, index, account, amount));
        require(_verify(proof, epochRoot[epochId], leaf), "RD: invalid proof");
        _claimedBitMap[epochId][index / 256] |= (uint256(1) << (index % 256));
        require(token.transfer(account, amount), "RD: transfer failed");
        emit Claimed(epochId, index, account, amount);
    }

    /// Vérification merkle à paires triées (ordre numérique des bytes32).
    function _verify(bytes32[] calldata proof, bytes32 root, bytes32 leaf) internal pure returns (bool) {
        bytes32 computed = leaf;
        for (uint256 i = 0; i < proof.length; i++) {
            bytes32 p = proof[i];
            computed = computed <= p
                ? sha256(abi.encodePacked(computed, p))
                : sha256(abi.encodePacked(p, computed));
        }
        return computed == root;
    }
}
