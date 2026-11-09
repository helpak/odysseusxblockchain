"""Benchmark tasks, generated and graded automatically.

Every task series is built from a seed: the numbers change with each series,
so the answers cannot be memorised or slipped into a prompt. The correct
answer is computed here, by the coordinator: miners only see the questions
and send back their raw answers, which are graded server-side.

Used for:
  - measuring proposed improvements (current prompt vs candidate);
  - the public benchmark every 2 h (network vs reference models).
"""

from __future__ import annotations

import random
import re
import unicodedata

ANSWER_INSTRUCTION = (
    "Answer the question. You MUST end with a last line in exactly this "
    "format: ANSWER: <final answer>"
)

DAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
WORDS = [
    "uncharacteristically", "encyclopedia", "extraordinary", "parallelogram",
    "development", "establishment", "rhinoceros", "kaleidoscope", "abracadabra",
    "commissioner", "hippopotamus", "electricity",
]


def _strip_accents(text: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", text) if unicodedata.category(c) != "Mn")


def _task_arith(r: random.Random) -> dict:
    a, b, c, d = r.randint(12, 99), r.randint(3, 19), r.randint(100, 999), r.randint(10, 99)
    return {"kind": "number", "q": f"Compute ({a} × {b}) + {c} − {d}.", "a": a * b + c - d}


def _task_percent(r: random.Random) -> dict:
    p = r.choice([5, 10, 12, 15, 20, 25, 30, 40, 75])
    base = r.randint(4, 60) * 20
    return {"kind": "number", "q": f"What is {p}% of {base}?", "a": base * p // 100}


def _task_train(r: random.Random) -> dict:
    v, h, m = r.randint(40, 140), r.randint(1, 5), r.choice([0, 30])
    dist = v * h + (v * m) // 60
    duration = f"{h} h" + (f" {m} min" if m else "")
    return {
        "kind": "number",
        "q": f"A train travels at a constant {v} km/h for {duration}. How far does it go, in km?",
        "a": dist,
    }


def _task_minutes(r: random.Random) -> dict:
    h = r.randint(1, 9)
    half = r.choice([0, 0.25, 0.5, 0.75])
    label = f"{h + half}".rstrip("0").rstrip(".")
    return {"kind": "number", "q": f"How many minutes are there in {label} hours?", "a": int((h + half) * 60)}


def _task_sequence(r: random.Random) -> dict:
    start, ratio, n = r.randint(1, 6), r.choice([2, 3]), r.randint(4, 5)
    seq = [start * ratio**i for i in range(n)]
    return {
        "kind": "number",
        "q": f"What is the next number in the sequence: {', '.join(map(str, seq))}, ?",
        "a": start * ratio**n,
    }


def _task_sort(r: random.Random) -> dict:
    nums = r.sample(range(1, 200), 6)
    return {
        "kind": "list",
        "q": f"Sort these numbers in ascending order: {', '.join(map(str, nums))}.",
        "a": sorted(nums),
    }


def _task_weekday(r: random.Random) -> dict:
    start, delta = r.randrange(7), r.randint(3, 40)
    return {
        "kind": "word",
        "q": f"If today is {DAYS[start]}, what day of the week will it be in {delta} days?",
        "a": DAYS[(start + delta) % 7],
    }


def _task_letters(r: random.Random) -> dict:
    word = r.choice(WORDS)
    letter = r.choice(sorted(set(word)))
    count = word.count(letter)
    return {
        "kind": "number",
        "q": f'How many times does the letter "{letter}" appear in the word "{word}"?',
        "a": count,
    }


def _task_equation(r: random.Random) -> dict:
    x, a, b = r.randint(2, 30), r.randint(2, 12), r.randint(1, 50)
    return {"kind": "number", "q": f"Solve: {a}x + {b} = {a * x + b}. What is x?", "a": x}


GENERATORS = [
    _task_arith, _task_percent, _task_train, _task_minutes, _task_sequence,
    _task_sort, _task_weekday, _task_letters, _task_equation,
]


def generate(seed: int, count: int) -> list[dict]:
    """Deterministic series: same seed => same questions and answers."""
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
    """What miners see: never the answer."""
    return [{"id": t["id"], "prompt": t["prompt"]} for t in tasks]


def _final_line(answer: str) -> str:
    text = str(answer or "")
    matches = re.findall(r"ANSWER\s*:\s*(.+)", text, flags=re.IGNORECASE)
    if matches:
        return matches[-1].strip()
    lines = [line.strip() for line in text.strip().splitlines() if line.strip()]
    return lines[-1] if lines else ""


def _numbers(text: str, thousands: bool = True) -> list[int]:
    # 1,000 / 1 000 -> 1000. Not for lists, where "12,150" means two numbers.
    cleaned = re.sub(r"(?<=\d)[,   ](?=\d{3}\b)", "", text) if thousands else text
    return [int(n) for n in re.findall(r"-?\d+", cleaned)]


def is_correct(task: dict, answer: str) -> bool:
    final = _final_line(answer)
    if task["kind"] == "number":
        nums = _numbers(final)
        return bool(nums) and nums[-1] == int(task["a"])
    if task["kind"] == "list":
        return _numbers(final, thousands=False) == list(task["a"])
    if task["kind"] == "word":
        return _strip_accents(task["a"]).lower() in _strip_accents(final).lower()
    return False


def score(tasks: list[dict], answers: dict) -> int:
    """answers: {task_id (str|int): raw answer}. Returns the number of correct answers."""
    by_id = {str(k): v for k, v in (answers or {}).items()}
    return sum(1 for t in tasks if is_correct(t, by_id.get(str(t["id"]), "")))
