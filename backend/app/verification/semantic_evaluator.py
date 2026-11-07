"""ASTRAVA V1.4: Tier 2 Semantic Evaluator (M1.4-3).

Evaluates agent deliverables semantically against declared task acceptance criteria
and schema requirements using Claude Haiku 5.5. Generates structured compliance scores,
unmet criteria lists, and remediation feedback.
"""

import json
import logging
import re
from typing import Any

from pydantic import BaseModel, Field

from app.config import settings
from app.providers.base import BaseProvider, ProviderRequest, ProviderResponse, ProviderStatus
from app.providers.claude_code import ClaudeCodeCLIProvider

logger = logging.getLogger("astrava.verification.semantic")


class SemanticEvaluationResult(BaseModel):
    passed: bool
    compliance_score: float = Field(..., ge=0.0, le=1.0)
    unmet_criteria: list[str] = Field(default_factory=list)
    reasoning: str = ""
    suggestions: list[str] = Field(default_factory=list)


def _extract_json_dict(text: str) -> dict[str, Any] | None:
    text_clean = text.strip()
    try:
        data = json.loads(text_clean)
        if isinstance(data, dict):
            return data
    except Exception:
        pass

    match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if match:
        try:
            data = json.loads(match.group(1))
            if isinstance(data, dict):
                return data
        except Exception:
            pass

    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1 and end > start:
        try:
            data = json.loads(text[start : end + 1])
            if isinstance(data, dict):
                return data
        except Exception:
            pass
    return None


class SemanticEvaluationProvider(BaseProvider):
    """Dedicated provider for Tier 2 Semantic Evaluation using Claude Haiku 5.5."""

    def __init__(self, model: str = "claude-haiku-5-5"):
        self.model = model
        self._delegate = ClaudeCodeCLIProvider()

    @property
    def name(self) -> str:
        return "semantic_evaluator"

    async def execute(self, request: ProviderRequest) -> ProviderResponse:
        if settings.APP_ENV == "test":
            return ProviderResponse(
                status=ProviderStatus.SUCCESS,
                exit_code=0,
                output_text=json.dumps(
                    {
                        "passed": True,
                        "compliance_score": 1.0,
                        "unmet_criteria": [],
                        "reasoning": "Criteria verified in deliverable (test environment default).",
                        "suggestions": [],
                    }
                ),
                input_tokens=50,
                output_tokens=30,
                duration_ms=10,
                cost_usd=0.0005,
            )
        req = request.model_copy(update={"model": self.model})
        return await self._delegate.execute(req)


class SemanticEvaluator:
    @classmethod
    async def evaluate(
        cls,
        deliverable_text: str,
        acceptance_criteria: list[str],
        task_title: str,
        task_description: str = "",
        provider: BaseProvider | None = None,
    ) -> SemanticEvaluationResult:
        """Semantically evaluates a deliverable against acceptance criteria.

        If acceptance_criteria is empty or absent, returns passed=True with score 1.0.
        """
        if not acceptance_criteria:
            return SemanticEvaluationResult(
                passed=True,
                compliance_score=1.0,
                unmet_criteria=[],
                reasoning="No explicit acceptance criteria specified; semantic check passed.",
                suggestions=[],
            )

        criteria_list_str = "\n".join(
            f"{i + 1}. {crit}" for i, crit in enumerate(acceptance_criteria)
        )

        prompt = f"""You are the ASTRAVA Senior Quality Assurance & Semantic Evaluator.
Evaluate the following deliverable against each declared acceptance criterion for task '{task_title}'.

## Task Description
{task_description or "N/A"}

## Declared Acceptance Criteria:
{criteria_list_str}

## Deliverable Content:
```
{deliverable_text[:6000]}
```

Instructions:
1. Objectively evaluate whether each criterion is met by the deliverable.
2. Calculate a compliance score between 0.0 and 1.0 (proportion of criteria fully satisfied).
3. Determine passed: true if compliance_score >= 0.8 and no critical criteria failed, else false.
4. List every unmet criterion exactly.
5. Provide concise reasoning and actionable suggestions for remediation.

Respond with ONLY valid JSON in the following format:
{{
  "passed": true,
  "compliance_score": 1.0,
  "unmet_criteria": [],
  "reasoning": "All acceptance criteria verified in deliverable.",
  "suggestions": []
}}
"""
        eval_provider = provider or SemanticEvaluationProvider()
        req = ProviderRequest(
            prompt=prompt,
            system_prompt="You are a strict, objective software evaluation engine. Output only JSON.",
            timeout_seconds=45,
        )

        try:
            resp = await eval_provider.execute(req)
            if resp.status != ProviderStatus.SUCCESS or not resp.output_text.strip():
                logger.warning(
                    "Semantic evaluation provider returned non-success (%s): %s",
                    resp.status,
                    resp.error_message,
                )
                # Fail closed on evaluation error if criteria existed
                return SemanticEvaluationResult(
                    passed=False,
                    compliance_score=0.0,
                    unmet_criteria=acceptance_criteria,
                    reasoning=f"Evaluation provider call failed: {resp.error_message or resp.status.value}",
                    suggestions=["Re-run deliverable generation or inspection"],
                )

            parsed = _extract_json_dict(resp.output_text)
            if not parsed:
                logger.warning("Could not parse JSON from evaluation output: %s", resp.output_text)
                return SemanticEvaluationResult(
                    passed=False,
                    compliance_score=0.5,
                    unmet_criteria=[
                        "Unable to verify criteria compliance due to unparseable evaluator response"
                    ],
                    reasoning="Semantic evaluator output was not valid JSON",
                    suggestions=["Check evaluator formatting"],
                )

            score = float(parsed.get("compliance_score", 0.0))
            score = max(0.0, min(1.0, score))
            unmet = list(parsed.get("unmet_criteria", []))
            passed = bool(parsed.get("passed", score >= 0.8 and not unmet))
            reasoning = str(parsed.get("reasoning", ""))
            suggestions = list(parsed.get("suggestions", []))

            return SemanticEvaluationResult(
                passed=passed,
                compliance_score=score,
                unmet_criteria=unmet,
                reasoning=reasoning,
                suggestions=suggestions,
            )
        except Exception as exc:
            logger.error("Exception during semantic evaluation of task %s: %s", task_title, exc)
            return SemanticEvaluationResult(
                passed=False,
                compliance_score=0.0,
                unmet_criteria=acceptance_criteria,
                reasoning=f"Semantic evaluation raised exception: {exc}",
                suggestions=["Inspect execution logs"],
            )
