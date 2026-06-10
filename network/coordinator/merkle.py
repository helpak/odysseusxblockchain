"""Arbre merkle sha256 à paires triées — miroir exact de RewardsDistributor.sol.

Feuille  : sha256(abi.encodePacked(uint256 epochId, uint256 index, address account, uint256 amount))
Nœud     : sha256(min(a, b) || max(a, b))
Impair   : le dernier nœud d'un niveau impair est promu tel quel au niveau supérieur.

sha256 (et non keccak256) a été choisi volontairement : il est disponible côté
contrat (précompilé EVM) ET dans hashlib en Python standard, donc le
coordinateur n'a besoin d'aucune dépendance crypto externe.

Utilisable en module (build_payout_tree) ou en CLI :
    python3 merkle.py build <epoch_id> <payouts.json>
où payouts.json = [{"account": "0x…", "amount": "<wei en décimal>"}, …]
"""

from __future__ import annotations

import hashlib
import json
import re
import sys

_ADDRESS_RE = re.compile(r"^0x[0-9a-fA-F]{40}$")


def normalize_address(account: str) -> str:
    account = account.strip()
    if not _ADDRESS_RE.match(account):
        raise ValueError(f"adresse invalide: {account!r}")
    return account.lower()


def leaf_hash(epoch_id: int, index: int, account: str, amount: int) -> bytes:
    """sha256(abi.encodePacked(uint256, uint256, address, uint256)) — 116 octets."""
    if epoch_id < 0 or index < 0 or amount < 0:
        raise ValueError("epoch_id, index et amount doivent être >= 0")
    account_bytes = bytes.fromhex(normalize_address(account)[2:])
    packed = (
        epoch_id.to_bytes(32, "big")
        + index.to_bytes(32, "big")
        + account_bytes
        + amount.to_bytes(32, "big")
    )
    return hashlib.sha256(packed).digest()


def pair_hash(a: bytes, b: bytes) -> bytes:
    """Hachage de paire triée, identique à RewardsDistributor._verify."""
    return hashlib.sha256(a + b if a <= b else b + a).digest()


def build_levels(leaves: list[bytes]) -> list[list[bytes]]:
    """Niveau 0 = feuilles ; dernier niveau = [racine]."""
    if not leaves:
        raise ValueError("aucune feuille")
    levels = [list(leaves)]
    while len(levels[-1]) > 1:
        current = levels[-1]
        nxt = []
        for i in range(0, len(current) - 1, 2):
            nxt.append(pair_hash(current[i], current[i + 1]))
        if len(current) % 2 == 1:
            nxt.append(current[-1])  # nœud impair promu sans frère
        levels.append(nxt)
    return levels


def proof_for(levels: list[list[bytes]], index: int) -> list[bytes]:
    proof = []
    idx = index
    for level in levels[:-1]:
        sibling = idx ^ 1
        if sibling < len(level):
            proof.append(level[sibling])
        idx //= 2
    return proof


def verify(proof: list[bytes], root: bytes, leaf: bytes) -> bool:
    computed = leaf
    for p in proof:
        computed = pair_hash(computed, p)
    return computed == root


def build_payout_tree(epoch_id: int, payouts: list[dict]) -> dict:
    """Construit l'arbre complet d'une époque.

    payouts: [{"account": "0x…", "amount": int|str}, …] — un seul payout par
    adresse (le coordinateur agrège par wallet avant d'appeler ici).
    Retourne {merkle_root, total_amount, claims: [{index, account, amount, proof}]}.
    """
    if not payouts:
        raise ValueError("aucun payout")
    entries = []
    seen = set()
    for p in payouts:
        account = normalize_address(p["account"])
        amount = int(p["amount"])
        if amount <= 0:
            raise ValueError(f"montant invalide pour {account}: {amount}")
        if account in seen:
            raise ValueError(f"adresse en double: {account} (agréger avant)")
        seen.add(account)
        entries.append((account, amount))
    # Ordre déterministe : l'index de chaque claim est stable et re-générable.
    entries.sort(key=lambda e: e[0])

    leaves = [leaf_hash(epoch_id, i, account, amount) for i, (account, amount) in enumerate(entries)]
    levels = build_levels(leaves)
    root = levels[-1][0]

    claims = []
    for i, (account, amount) in enumerate(entries):
        proof = proof_for(levels, i)
        assert verify(proof, root, leaves[i]), "auto-vérification merkle échouée"
        claims.append(
            {
                "index": i,
                "account": account,
                "amount": str(amount),
                "proof": ["0x" + p.hex() for p in proof],
            }
        )

    return {
        "epoch_id": epoch_id,
        "merkle_root": "0x" + root.hex(),
        "total_amount": str(sum(amount for _, amount in entries)),
        "claims": claims,
    }


def _main(argv: list[str]) -> int:
    if len(argv) == 4 and argv[1] == "build":
        epoch_id = int(argv[2])
        with open(argv[3], encoding="utf-8") as fh:
            payouts = json.load(fh)
        print(json.dumps(build_payout_tree(epoch_id, payouts), indent=2))
        return 0
    print(__doc__, file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(_main(sys.argv))
