"""Answer-quality eval: ask the deployed assistant real questions and grade the answers.

`kb eval` checks retrieval only (did search find the right page?). This checks what students
see: each case in evals/answers.yaml goes through the same streaming pipeline as the website and
Slack, by invoking the chat function with {"stream": true}, and the answer is graded on:

- cite:     at least one cited source URL contains one of these fragments
- include:  every pattern appears in the answer (regex, case-insensitive; use a|b for synonyms)
- exclude:  no pattern appears in the answer
- rubric:   criteria a model judges against the answer and its sources, for what patterns can't
            check ("doesn't name specific teams as best without a source")

Fixed checks run first and are free. Rubric grading calls the same Claude model the assistant
uses (read from the chat function's settings) unless --grader-model says otherwise. Grading with
the model that wrote the answer can be lenient, so rubric criteria are written as narrow yes/no
facts, and a failed fixed check fails the case whatever the grader says.

A run costs roughly a cent per case (answer plus grading). Results go to build/evals/ as JSON so
runs can be compared, e.g. before and after a model or prompt change.
"""

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml

GRADE_TOOL = {
    "name": "record_grades",
    "description": "Record whether the answer meets each numbered criterion.",
    "input_schema": {
        "type": "object",
        "properties": {
            "grades": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "criterion": {"type": "integer", "description": "The criterion's number."},
                        "met": {"type": "boolean"},
                        "reason": {"type": "string", "description": "One short sentence."},
                    },
                    "required": ["criterion", "met", "reason"],
                },
            }
        },
        "required": ["grades"],
    },
}

GRADER_SYSTEM = """\
You grade answers from an FRC (FIRST Robotics Competition) design assistant for high school \
students. For each numbered criterion, decide whether the answer meets it. Judge only what the \
answer actually says, strictly and literally; don't give credit for what it might have meant. \
Use the listed sources only to understand what the answer cited. Record every criterion with the \
record_grades tool."""


@dataclass(frozen=True)
class Case:
    id: str
    question: str
    tags: tuple[str, ...] = ()
    cite: tuple[str, ...] = ()
    include: tuple[str, ...] = ()
    exclude: tuple[str, ...] = ()
    rubric: tuple[str, ...] = ()


@dataclass
class Result:
    case: Case
    answer: str = ""
    sources: list[dict] = field(default_factory=list)
    failures: list[str] = field(default_factory=list)
    cost_usd: float = 0.0

    @property
    def passed(self) -> bool:
        return not self.failures


def load_cases(path: Path) -> list[Case]:
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    cases, seen = [], set()
    for entry in data.get("cases") or []:
        case = Case(
            id=str(entry["id"]),
            question=str(entry["question"]).strip(),
            tags=tuple(entry.get("tags") or ()),
            cite=tuple(entry.get("cite") or ()),
            include=tuple(entry.get("include") or ()),
            exclude=tuple(entry.get("exclude") or ()),
            rubric=tuple(entry.get("rubric") or ()),
        )
        short = [c for c in case.rubric if len(c.split()) < 3]
        if short:
            raise ValueError(f"{case.id}: rubric criterion {short[0]!r} is too short (an unquoted '#' starts a YAML comment)")
        if case.id in seen:
            raise ValueError(f"duplicate case id {case.id!r}")
        for pattern in case.include + case.exclude:
            re.compile(pattern)  # fail on a typo before spending anything
        seen.add(case.id)
        cases.append(case)
    return cases


def fixed_checks(case: Case, answer: str, sources: list[dict]) -> list[str]:
    """Failures from the free checks: citations, required and forbidden text."""
    failures = []
    urls = [str(s.get("url", "")) for s in sources]
    if case.cite and not any(fragment in url for fragment in case.cite for url in urls):
        failures.append(f"cites none of {list(case.cite)}")
    for pattern in case.include:
        if not re.search(pattern, answer, re.IGNORECASE):
            failures.append(f"missing /{pattern}/")
    for pattern in case.exclude:
        match = re.search(pattern, answer, re.IGNORECASE)
        if match:
            failures.append(f"says {match.group(0)!r} (/{pattern}/)")
    return failures


def grading_prompt(case: Case, answer: str, sources: list[dict]) -> str:
    cited = "\n".join(f"[{s.get('number')}] {s.get('title')} ({s.get('url')})" for s in sources) or "(none)"
    criteria = "\n".join(f"{i}. {criterion}" for i, criterion in enumerate(case.rubric, 1))
    return (
        f"<question>\n{case.question}\n</question>\n\n<answer>\n{answer}\n</answer>\n\n"
        f"<cited_sources>\n{cited}\n</cited_sources>\n\n<criteria>\n{criteria}\n</criteria>"
    )


def rubric_failures(case: Case, grades: list[dict]) -> list[str]:
    by_number = {int(g.get("criterion", 0)): g for g in grades}
    failures = []
    for i, criterion in enumerate(case.rubric, 1):
        grade = by_number.get(i)
        if grade is None:
            failures.append(f"ungraded: {criterion}")
        elif not grade.get("met"):
            failures.append(f"rubric: {criterion} ({grade.get('reason', '').strip()})")
    return failures


def grade(claude, model: str, case: Case, answer: str, sources: list[dict]) -> tuple[list[dict], dict]:
    """Ask the grader model about each rubric criterion. Returns (grades, usage)."""
    message = claude.messages.create(
        model=model,
        max_tokens=1024,
        system=GRADER_SYSTEM,
        tools=[GRADE_TOOL],
        tool_choice={"type": "tool", "name": GRADE_TOOL["name"]},
        messages=[{"role": "user", "content": grading_prompt(case, answer, sources)}],
    )
    grades = next((block.input.get("grades", []) for block in message.content if block.type == "tool_use"), [])
    usage = {"input_tokens": message.usage.input_tokens, "output_tokens": message.usage.output_tokens}
    return grades, usage


def run_case(case: Case, ask, grader=None) -> Result:
    """ask(question) -> (status, body); grader(case, answer, sources) -> (grades, cost_usd)."""
    result = Result(case)
    status, body = ask(case.question)
    if status != 200:
        result.failures.append(f"HTTP {status}: {body.get('error', body)}")
        return result
    result.answer, result.sources = body.get("answer", ""), body.get("sources", [])
    result.cost_usd = float(body.get("usage", {}).get("cost_usd", 0))
    result.failures = fixed_checks(case, result.answer, result.sources)
    if case.rubric and grader:
        try:
            grades, cost = grader(case, result.answer, result.sources)
        except Exception as error:  # e.g. throttled after retries; the rest of the run still counts
            result.failures.append(f"grading failed: {type(error).__name__}: {error}"[:300])
        else:
            result.cost_usd += cost
            result.failures += rubric_failures(case, grades)
    return result


def summary(results: list[Result]) -> str:
    lines = []
    for r in results:
        lines.append(f"{'pass' if r.passed else 'FAIL'}  {r.case.id}")
        lines += [f"        - {failure}" for failure in r.failures]
    tags = sorted({t for r in results for t in r.case.tags})
    lines.append("")
    for tag in tags:
        tagged = [r for r in results if tag in r.case.tags]
        lines.append(f"  {tag:<12} {sum(r.passed for r in tagged)}/{len(tagged)}")
    total_cost = sum(r.cost_usd for r in results)
    lines.append(f"passed {sum(r.passed for r in results)}/{len(results)}, cost ${total_cost:.3f}")
    return "\n".join(lines)


def report(results: list[Result], model: str, grader_model: str) -> dict:
    return {
        "model": model,
        "grader_model": grader_model,
        "passed": sum(r.passed for r in results),
        "total": len(results),
        "cost_usd": round(sum(r.cost_usd for r in results), 4),
        "cases": [
            {
                "id": r.case.id,
                "passed": r.passed,
                "failures": r.failures,
                "answer": r.answer,
                "sources": [{"title": s.get("title"), "url": s.get("url")} for s in r.sources],
            }
            for r in results
        ],
    }


def dumps(data: dict) -> str:
    return json.dumps(data, indent=2, ensure_ascii=False) + "\n"
