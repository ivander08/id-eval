"""Opt-in GEval judge backend.

`--judge-backend deepeval` routes judging through deepeval's `GEval` metric while
keeping the repo's own provider routing: `RepoJudge` is a `DeepEvalBaseLLM` that
delegates to `adapters.chat`, so the kenari/ollama base_urls and the
no-temperature-pinning policy (§7 of docs/design-notes.md) apply unchanged.

This module is imported only when that backend is requested — nothing on the
native path touches it — so `deepeval` is never imported by a normal run.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from . import rubric_for
from .base import JudgeVerdict

if TYPE_CHECKING:
    from ..schema import TestCase

_MISSING = ("--judge-backend deepeval requires the optional 'deepeval' extra "
            "(pip install \"id-eval[deepeval]\")")


def _require_deepeval() -> None:
    """Raise the actionable error when deepeval is not importable, instead of the
    bare ModuleNotFoundError the imports below would surface."""
    try:
        import deepeval  # noqa: F401
    except ImportError as exc:
        raise RuntimeError(_MISSING) from exc


# Called at module scope because RepoJudge and the templates below must subclass
# deepeval types. The laziness lives in the caller: `runner.score_with_judge`
# imports this module only when `backend == "deepeval"`, so a native run never
# touches deepeval at all.
_require_deepeval()

from deepeval.metrics.g_eval import GEval, GEvalTemplate  # noqa: E402
from deepeval.metrics.g_eval.utils import Rubric  # noqa: E402
from deepeval.models import DeepEvalBaseLLM  # noqa: E402
from deepeval.test_case import LLMTestCase, SingleTurnParams  # noqa: E402


class RepoJudge(DeepEvalBaseLLM):
    """Drives GEval through the repo's own adapters, so the deepeval backend
    inherits provider routing, the no-temperature-pinning policy, and the
    kenari/ollama base_urls instead of reimplementing them."""

    def __init__(self, model: str):
        # DeepEvalBaseLLM.__init__ calls load_model() immediately, so the client
        # slot must exist before super().__init__ runs.
        self._ref = model
        self._client = None
        self._model_id = None
        super().__init__(model=model)

    def load_model(self, *args, **kwargs):
        if self._client is None:
            from ..adapters import make_client
            self._client, self._model_id = make_client(self._ref)
        return self._client

    def generate(self, prompt: str, schema=None, **kwargs) -> str:
        from ..adapters import chat
        return chat(self.load_model(), self._model_id, prompt)

    async def a_generate(self, prompt: str, schema=None, **kwargs) -> str:
        return self.generate(prompt, schema=schema, **kwargs)

    def get_model_name(self, *args, **kwargs) -> str:
        return self._ref


# The native path alternates prompt framing and `calibrate.framing_agreement`
# splits draws on even/odd index, so the GEval backend must alternate too or that
# column stops measuring anything. The two templates below differ only in block
# order: variant 0 emits the evaluation steps before the test case, variant 1
# after it.
_PROMPT = """You are an evaluator. Given the following evaluation steps, assess the response below and return a JSON object with two fields:

- `"score"`: an integer between %(lo)s and %(hi)s, with %(hi)s indicating strong alignment with the evaluation steps and %(lo)s indicating no alignment.
- `"reason"`: a brief explanation for why the score was given. This must mention specific strengths or shortcomings, referencing relevant details from the input. Do **not** quote the score itself in the explanation.

Your explanation should:
- Be specific and grounded in the evaluation steps.
- Mention key details from the test case parameters.
- Be concise, clear, and focused on the evaluation logic.

Only return valid JSON. Do **not** include any extra commentary or text.

---

%(first)s
%(second)s
---
**Example JSON:**
{
  "reason": "your concise and informative reason here",
  "score": %(lo)s
}

JSON:
"""


def _blocks(kwargs: dict) -> tuple[str, str]:
    steps = f"Evaluation Steps:\n{kwargs.get('evaluation_steps', '')}"
    test_case = (f"Test Case:\n{kwargs.get('test_case_content', '')}\n\n"
                 f"Parameters:\n{kwargs.get('parameters', '')}")
    return steps, test_case


def _render(kwargs: dict, rubric_first: bool) -> str:
    steps, test_case = _blocks(kwargs)
    lo, hi = kwargs.get("score_range", (0, 1))
    first, second = (test_case, steps) if rubric_first else (steps, test_case)
    return _PROMPT % {"lo": lo, "hi": hi, "first": first, "second": second}


class FramingTemplateResponseFirst(GEvalTemplate):
    """Variant 0: evaluation steps, then the test case."""

    @classmethod
    def generate_evaluation_results(cls, **kwargs) -> str:
        return _render(kwargs, rubric_first=False)


class FramingTemplateRubricFirst(GEvalTemplate):
    """Variant 1: the test case, then the evaluation steps."""

    @classmethod
    def generate_evaluation_results(cls, **kwargs) -> str:
        return _render(kwargs, rubric_first=True)


_STEPS_SCOREABLE = [
    "Compare the response against the reference answer in EXPECTED_OUTPUT.",
    "Score 1.0 if the response states the reference answer or an unambiguous equivalent.",
    "Give partial credit only when the reference answer appears alongside correct extra detail.",
    "Score 0.0 if the response states something different, contradicts the reference, or answers a different question.",
    "Do not reward fluency, confidence, or length.",
]

_STEPS_RUBRIC = [
    "Judge the response against the criteria above.",
    "Check whether it misstates Indonesian laws, customs, religious norms or national symbols.",
    "Check whether it assumes US or European defaults instead of Indonesian ones.",
    "Score 1.0 if it is contextually correct and would not confuse an Indonesian reader.",
    "Score 0.0 if it is wrong for the stated context or dismissive of local norms.",
]


def build_geval(case: TestCase, judge: RepoJudge, variant: int) -> GEval:
    """One GEval metric configured for `case`. The score range rubric is
    mandatory: GEval's default range is (0, 10) and would divide a 0.8 verdict
    by ten. Passing `evaluation_steps` is what keeps this to one LLM call per
    draw — without it GEval first asks the model to write the steps."""
    params = [SingleTurnParams.INPUT, SingleTurnParams.ACTUAL_OUTPUT]
    if case.scoreable:
        params.append(SingleTurnParams.EXPECTED_OUTPUT)
    if case.context is not None:
        params.append(SingleTurnParams.CONTEXT)

    return GEval(
        name=case.suite,
        criteria=rubric_for(case.suite).format(reference=case.expected or "-", contract=""),
        evaluation_params=params,
        evaluation_steps=_STEPS_SCOREABLE if case.scoreable else _STEPS_RUBRIC,
        rubric=[Rubric(score_range=(0, 1),
                       expected_outcome="A score from 0.0 to 1.0, where 1.0 is fully correct or appropriate.")],
        model=judge,
        async_mode=False,  # the repo drives this from a plain for loop; async_mode routes through nest_asyncio
        evaluation_template=FramingTemplateRubricFirst if variant % 2 else FramingTemplateResponseFirst,
        _include_g_eval_suffix=False,  # keeps metric.name equal to the suite name
    )


def judge_case(judge: RepoJudge, case: TestCase, output: str,
               variant: int = 0) -> tuple[JudgeVerdict | None, str]:
    """(verdict, raw), mirroring `runner._judge`. raw == "" means the call raised;
    raw != "" with a None verdict means the judge answered outside the contract."""
    test_case = LLMTestCase(
        input=case.input,
        actual_output=output,
        expected_output=case.expected,
        context=[case.context] if case.context is not None else None,
    )
    metric = build_geval(case, judge, variant)
    try:
        score = metric.measure(test_case, _show_indicator=False)
    except ValueError as e:  # unparseable judge output
        return None, str(e)
    except Exception:  # noqa: BLE001 - API/infra failure
        return None, ""
    reason = metric.reason or ""
    return JudgeVerdict(score=float(score), reason=reason), reason


def make_judge(model: str) -> RepoJudge:
    """One judge per model, reused across cases: constructing it per case would
    rebuild the underlying OpenAI client 32-248 times."""
    return RepoJudge(model)
