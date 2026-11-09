"""Tâches de benchmark générées et corrigées automatiquement.

Chaque série de tâches est fabriquée à partir d'une graine : les nombres
changent à chaque série, donc les réponses ne peuvent pas être apprises par
cœur ni glissées dans un prompt. La bonne réponse est calculée ici, par le
coordinateur : les mineurs ne voient que les questions et renvoient leurs
réponses brutes, qui sont corrigées côté serveur.

Utilisé pour :
  - mesurer les améliorations proposées (prompt actuel vs candidat) ;
  - le benchmark public toutes les 2 h (réseau vs modèles de référence).
"""

from __future__ import annotations

import random
import re
import unicodedata

ANSWER_INSTRUCTION = (
    "Réponds à la question. Termine OBLIGATOIREMENT par une dernière ligne au "
    "format exact : RÉPONSE: <réponse finale>"
)

DAYS = ["lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche"]
WORDS = [
    "anticonstitutionnellement", "bibliothèque", "extraordinaire", "parallélépipède",
    "développement", "établissement", "rhinocéros", "kaléidoscope", "abracadabra",
    "commissariat", "hippopotame", "électricité",
]


def _strip_accents(text: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", text) if unicodedata.category(c) != "Mn")


def _task_arith(r: random.Random) -> dict:
    a, b, c, d = r.randint(12, 99), r.randint(3, 19), r.randint(100, 999), r.randint(10, 99)
    return {"kind": "number", "q": f"Calcule ({a} × {b}) + {c} − {d}.", "a": a * b + c - d}


def _task_percent(r: random.Random) -> dict:
    p = r.choice([5, 10, 12, 15, 20, 25, 30, 40, 75])
    base = r.randint(4, 60) * 20
    return {"kind": "number", "q": f"Combien font {p} % de {base} ?", "a": base * p // 100}


def _task_train(r: random.Random) -> dict:
    v, h, m = r.randint(40, 140), r.randint(1, 5), r.choice([0, 30])
    dist = v * h + (v * m) // 60
    duration = f"{h} h" + (f" {m} min" if m else "")
    return {
        "kind": "number",
        "q": f"Un train roule à vitesse constante de {v} km/h pendant {duration}. Quelle distance parcourt-il, en km ?",
        "a": dist,
    }


def _task_minutes(r: random.Random) -> dict:
    h = r.randint(1, 9)
    half = r.choice([0, 0.25, 0.5, 0.75])
    label = f"{h + half}".replace(".", ",").rstrip("0").rstrip(",")
    return {"kind": "number", "q": f"Combien y a-t-il de minutes dans {label} heures ?", "a": int((h + half) * 60)}


def _task_sequence(r: random.Random) -> dict:
    start, ratio, n = r.randint(1, 6), r.choice([2, 3]), r.randint(4, 5)
    seq = [start * ratio**i for i in range(n)]
    return {
        "kind": "number",
        "q": f"Quel est le nombre suivant dans la suite : {', '.join(map(str, seq))}, ?",
        "a": start * ratio**n,
    }


def _task_sort(r: random.Random) -> dict:
    nums = r.sample(range(1, 200), 6)
    return {
        "kind": "list",
        "q": f"Range ces nombres dans l'ordre croissant : {', '.join(map(str, nums))}.",
        "a": sorted(nums),
    }


def _task_weekday(r: random.Random) -> dict:
    start, delta = r.randrange(7), r.randint(3, 40)
    return {
        "kind": "word",
        "q": f"Si aujourd'hui est {DAYS[start]}, quel jour de la semaine serons-nous dans {delta} jours ?",
        "a": DAYS[(start + delta) % 7],
    }


def _task_letters(r: random.Random) -> dict:
    word = r.choice(WORDS)
    letter = r.choice(sorted(set(_strip_accents(word)) - {"-"}))
    count = _strip_accents(word).count(letter)
    return {
        "kind": "number",
        "q": f"Combien de fois la lettre « {letter} » apparaît-elle dans le mot « {word} » (accents ignorés) ?",
        "a": count,
    }


def _task_equation(r: random.Random) -> dict:
    x, a, b = r.randint(2, 30), r.randint(2, 12), r.randint(1, 50)
    return {"kind": "number", "q": f"Résous : {a}x + {b} = {a * x + b}. Que vaut x ?", "a": x}


GENERATORS = [
    _task_arith, _task_percent, _task_train, _task_minutes, _task_sequence,
    _task_sort, _task_weekday, _task_letters, _task_equation,
]


def generate(seed: int, count: int) -> list[dict]:
    """Série déterministe : même graine => mêmes questions et réponses."""
    r = random.Random(seed)
    tasks = []
    for i in range(count):
        task = GENERATORS[i % len(GENERATORS)](r)
        task["id"] = i
        task["prompt"] = f"{task['q']}\n\n{ANSWER_INSTRUCTION}"
        tasks.append(task)
    r.shuffle(tasks)
    return tasks


def public_view(tasks: list[dict]) -> list[dict]:
    """Ce que voient les mineurs : jamais la réponse."""
    return [{"id": t["id"], "prompt": t["prompt"]} for t in tasks]


def _final_line(answer: str) -> str:
    text = str(answer or "")
    matches = re.findall(r"R[ÉE]PONSE\s*:\s*(.+)", text, flags=re.IGNORECASE)
    if matches:
        return matches[-1].strip()
    lines = [line.strip() for line in text.strip().splitlines() if line.strip()]
    return lines[-1] if lines else ""


def _numbers(text: str) -> list[int]:
    cleaned = re.sub(r"(?<=\d)[   ](?=\d{3}\b)", "", text)  # 1 000 -> 1000
    return [int(n) for n in re.findall(r"-?\d+", cleaned)]


def is_correct(task: dict, answer: str) -> bool:
    final = _final_line(answer)
    if task["kind"] == "number":
        nums = _numbers(final)
        return bool(nums) and nums[-1] == int(task["a"])
    if task["kind"] == "list":
        return _numbers(final) == list(task["a"])
    if task["kind"] == "word":
        return _strip_accents(task["a"]).lower() in _strip_accents(final).lower()
    return False


def score(tasks: list[dict], answers: dict) -> int:
    """answers : {task_id (str|int): réponse brute}. Retourne le nombre de bonnes réponses."""
    by_id = {str(k): v for k, v in (answers or {}).items()}
    return sum(1 for t in tasks if is_correct(t, by_id.get(str(t["id"]), "")))
