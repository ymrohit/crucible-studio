"""Curated, edge-heavy, function-level benchmark problems.

Each problem fully specifies its behavioral contract (including edge cases) in the prompt so
both conditions know the rules — the benchmark measures correct *implementation*, which is
where vanilla silently faceplants and the Crucible loop catches the bug. The ``hidden_tests``
are the scorer's ground truth and are NEVER shown to the loop (the loop sees only its own
Adversary-generated oracle).

NB (honesty, per §11): this is an ILLUSTRATIVE curated set for the demo, not a
contamination-free LiveCodeBench slice. The real LCB number is a separate, optional run —
load it with `run_offline.py --problems <file.jsonl>`. Curating a demo set is fine; never
present this as the benchmark number.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Problem:
    id: str
    prompt: str
    function_name: str
    hidden_tests: list[tuple[str, str]] = field(default_factory=list)  # (input_repr, expected_repr)
    hidden_checker: str = ""   # alternative: a `def check(candidate)` harness (HumanEval/LeetCode)
    note: str = ""
    difficulty: str = ""


BUILTIN_PROBLEMS: list[Problem] = [
    Problem(
        id="merge_intervals",
        function_name="merge_intervals",
        prompt=(
            "Implement `def merge_intervals(intervals: list[tuple[int, int]]) -> list[tuple[int, int]]:` "
            "that merges all overlapping intervals and returns them sorted by start. "
            "TOUCHING intervals must be merged: (1,4) and (4,5) become (1,5). "
            "Intervals may be unsorted; nested intervals collapse into the enclosing one; "
            "an empty input returns an empty list."
        ),
        hidden_tests=[
            ("[(1,3),(2,6),(8,10),(15,18)]", "[(1,6),(8,10),(15,18)]"),
            ("[(1,4),(4,5)]", "[(1,5)]"),          # touching edge — the classic miss
            ("[]", "[]"),
            ("[(1,4)]", "[(1,4)]"),
            ("[(1,10),(2,3),(4,5)]", "[(1,10)]"),  # nested
            ("[(6,8),(1,9),(2,4),(4,7)]", "[(1,9)]"),  # unsorted, all overlap
        ],
        note="touching-edge off-by-one is the reliable vanilla miss",
    ),
    Problem(
        id="paginate",
        function_name="paginate",
        prompt=(
            "Implement `def paginate(items: list, page_size: int, page: int) -> list:` returning the "
            "items on the given 1-INDEXED page. page=1 is the first page. A page beyond the last "
            "returns an empty list. The final page may be partial. If page_size exceeds the number "
            "of items, page 1 returns all items. An empty items list returns an empty list."
        ),
        hidden_tests=[
            ("[1,2,3,4,5], 2, 1", "[1,2]"),
            ("[1,2,3,4,5], 2, 3", "[5]"),     # last partial page
            ("[1,2,3,4,5], 2, 4", "[]"),      # beyond range
            ("[], 3, 1", "[]"),
            ("[1,2,3], 5, 1", "[1,2,3]"),     # page_size > len
            ("[1,2,3,4,5,6], 3, 2", "[4,5,6]"),
        ],
        note="1-indexed off-by-one and beyond-range are common misses",
    ),
    Problem(
        id="roman_to_int",
        function_name="roman_to_int",
        prompt=(
            "Implement `def roman_to_int(s: str) -> int:` converting a valid Roman numeral string "
            "(I,V,X,L,C,D,M) to its integer value. Handle the subtractive forms IV, IX, XL, XC, "
            "CD, CM correctly."
        ),
        hidden_tests=[
            ("'III'", "3"), ("'IV'", "4"), ("'IX'", "9"), ("'LVIII'", "58"),
            ("'MCMXCIV'", "1994"), ("'MMMCMXCIX'", "3999"), ("'XL'", "40"), ("'CD'", "400"),
        ],
        note="subtractive notation is the catch",
    ),
    Problem(
        id="valid_parentheses",
        function_name="is_valid",
        prompt=(
            "Implement `def is_valid(s: str) -> bool:` returning whether the string of brackets "
            "'()[]{}' is balanced: every opener is closed by the matching closer in the correct "
            "order. The empty string is valid (True). A string with a leftover opener is invalid."
        ),
        hidden_tests=[
            ("'()'", "True"), ("'()[]{}'", "True"), ("'(]'", "False"),
            ("'([)]'", "False"), ("'{[]}'", "True"), ("''", "True"),
            ("'('", "False"), ("']'", "False"),
        ],
        note="empty-valid and interleaved mismatch are the catches",
    ),
    Problem(
        id="flatten",
        function_name="flatten",
        prompt=(
            "Implement `def flatten(nested: list) -> list:` that fully flattens an arbitrarily "
            "nested list of integers into a single flat list, preserving left-to-right order. "
            "Empty lists contribute nothing. A flat list is returned unchanged."
        ),
        hidden_tests=[
            ("[1,[2,[3,4],5]]", "[1,2,3,4,5]"),
            ("[]", "[]"),
            ("[[],[1],[[2]]]", "[1,2]"),
            ("[1,2,3]", "[1,2,3]"),
            ("[[[[1]]]]", "[1]"),
        ],
        note="deep nesting + empty sublists",
    ),
    Problem(
        id="palindrome_permutation",
        function_name="can_form_palindrome",
        prompt=(
            "Implement `def can_form_palindrome(s: str) -> bool:` returning whether the characters "
            "of s can be rearranged into a palindrome. At most one character may have an odd count. "
            "The empty string returns True. Treat characters case-sensitively."
        ),
        hidden_tests=[
            ("'aab'", "True"), ("'abc'", "False"), ("'a'", "True"),
            ("''", "True"), ("'aabb'", "True"), ("'Aa'", "False"),
            ("'carerac'", "True"),
        ],
        note="at-most-one-odd rule + empty",
    ),
]


def get_builtin() -> list[Problem]:
    return list(BUILTIN_PROBLEMS)
