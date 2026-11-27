from pathlib import Path
from types import SimpleNamespace

import pytest

from frcrag.answer_eval import Case, fixed_checks, grade, grading_prompt, load_cases, report, rubric_failures, run_case, summary

ROOT = Path(__file__).parents[1]
SOURCES = [{"number": 1, "title": "2026 Game Manual R103", "url": "https://x/2026GameManual.htm#R103"}]


def test_the_repo_eval_file_loads_and_every_case_checks_something():
    cases = load_cases(ROOT / "evals" / "answers.yaml")
    assert len(cases) >= 25
    assert all(c.cite or c.include or c.exclude or c.rubric for c in cases)
    assert {"design", "rules", "history", "honesty", "safety"} <= {t for c in cases for t in c.tags}


def test_duplicate_ids_and_bad_patterns_are_rejected(tmp_path):
    path = tmp_path / "a.yaml"
    path.write_text("cases:\n  - {id: a, question: q}\n  - {id: a, question: r}\n", encoding="utf-8")
    with pytest.raises(ValueError, match="duplicate"):
        load_cases(path)
    path.write_text("cases:\n  - {id: a, question: q, include: ['(unclosed']}\n", encoding="utf-8")
    with pytest.raises(Exception):
        load_cases(path)


def test_fixed_checks():
    case = Case(id="w", question="q", cite=("#R103",), include=("115", "R103"), exclude=("RAPID REACT",))
    assert fixed_checks(case, "The limit is 115 lb (R103) [1].", SOURCES) == []
    failures = fixed_checks(case, "In RAPID REACT it was 120 lb.", [{"url": "https://x/other"}])
    assert failures[0] == "cites none of ['#R103']"
    assert "missing /115/" in failures and "missing /R103/" in failures
    assert any("RAPID REACT" in f for f in failures)


def test_include_is_case_insensitive_with_alternatives():
    case = Case(id="c", question="q", include=("charged up|2023",))
    assert fixed_checks(case, "That was Charged Up.", []) == []


def test_rubric_failures_name_the_criterion_and_reason():
    case = Case(id="r", question="q", rubric=("Says A.", "Says B.", "Says C."))
    grades = [{"criterion": 1, "met": True, "reason": "ok"}, {"criterion": 2, "met": False, "reason": "it says D"}]
    assert rubric_failures(case, grades) == ["rubric: Says B. (it says D)", "ungraded: Says C."]


def test_grading_prompt_numbers_criteria_and_lists_sources():
    prompt = grading_prompt(Case(id="r", question="Weight?", rubric=("Says A.", "Says B.")), "115 lb", SOURCES)
    assert "1. Says A.\n2. Says B." in prompt
    assert "[1] 2026 Game Manual R103 (https://x/2026GameManual.htm#R103)" in prompt
    assert "<answer>\n115 lb\n</answer>" in prompt


class FakeClaude:
    def __init__(self, grades):
        self.calls = []
        self.messages = self
        self._grades = grades

    def create(self, **kwargs):
        self.calls.append(kwargs)
        block = SimpleNamespace(type="tool_use", input={"grades": self._grades})
        return SimpleNamespace(content=[block], usage=SimpleNamespace(input_tokens=500, output_tokens=80))


def test_grade_forces_the_grading_tool():
    claude = FakeClaude([{"criterion": 1, "met": True, "reason": "yes"}])
    grades, usage = grade(claude, "model-x", Case(id="r", question="q", rubric=("Says A.",)), "answer", SOURCES)
    assert grades[0]["met"] and usage == {"input_tokens": 500, "output_tokens": 80}
    call = claude.calls[0]
    assert call["model"] == "model-x" and call["tool_choice"] == {"type": "tool", "name": "record_grades"}


def ok(answer, sources=SOURCES, cost=0.005):
    return lambda question: (200, {"answer": answer, "sources": sources, "usage": {"cost_usd": cost}})


def test_run_case_combines_checks_and_grading():
    case = Case(id="w", question="q", include=("115",), rubric=("Says A.",))
    graded = run_case(case, ok("115 lb"), lambda c, a, s: ([{"criterion": 1, "met": False, "reason": "no A"}], 0.001))
    assert not graded.passed and graded.failures == ["rubric: Says A. (no A)"]
    assert graded.cost_usd == pytest.approx(0.006)
    assert run_case(Case(id="x", question="q", include=("115",)), ok("115 lb")).passed


def test_run_case_reports_errors_without_grading():
    calls = []
    result = run_case(Case(id="e", question="q", rubric=("A",)), lambda q: (502, {"error": "boom"}), lambda *a: calls.append(a))
    assert result.failures == ["HTTP 502: boom"] and not calls


def test_summary_and_report():
    results = [
        run_case(Case(id="a", question="q", tags=("rules",), include=("115",)), ok("115")),
        run_case(Case(id="b", question="q", tags=("rules",), include=("115",)), ok("120")),
    ]
    text = summary(results)
    assert "pass  a" in text and "FAIL  b" in text and "- missing /115/" in text
    assert "rules        1/2" in text and "passed 1/2" in text
    data = report(results, "m", "g")
    assert data["passed"] == 1 and data["cases"][1]["failures"] == ["missing /115/"]


def test_a_grading_error_fails_only_that_case():
    def throttled(case, answer, sources):
        raise RuntimeError("429 Too many requests")

    result = run_case(Case(id="t", question="q", rubric=("A",)), ok("answer"), throttled)
    assert result.failures == ["grading failed: RuntimeError: 429 Too many requests"]


def test_a_criterion_cut_short_by_a_yaml_comment_is_caught(tmp_path):
    path = tmp_path / "a.yaml"
    path.write_text("cases:\n  - id: a\n    question: q\n    rubric:\n      - Says #25 chain is common.\n", encoding="utf-8")
    with pytest.raises(ValueError, match="too short"):
        load_cases(path)
