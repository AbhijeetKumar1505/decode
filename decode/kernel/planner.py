from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field


class WorkflowStep(BaseModel):
    id: str
    description: str
    suggested_skill: Optional[str] = None
    params: Dict[str, Any] = Field(default_factory=dict)
    depends_on: List[str] = Field(default_factory=list)
    status: str = "pending"


class Workflow(BaseModel):
    goal: str
    steps: List[WorkflowStep] = Field(default_factory=list)
    reasoning: str = ""


class Planner:
    DECOMPOSITION_PROMPT = """You are a security workflow planner. Decompose the user's goal into a sequence of analysis steps.

User goal: {goal}

Available skills: {skills_summary}

Output ONLY valid JSON:
{{
  "reasoning": "Explain your decomposition strategy",
  "steps": [
    {{
      "id": "step-1",
      "description": "Clear description of what this step does",
      "suggested_skill": "skill_name or null if no specific skill",
      "params": {{}},
      "depends_on": []
    }}
  ]
}}"""

    def __init__(self, provider=None):
        self._provider = provider

    def set_provider(self, provider):
        self._provider = provider

    async def decompose(self, goal: str, skills_summary: str) -> Workflow:
        if not self._provider:
            return self._default_decompose(goal)
        prompt = self.DECOMPOSITION_PROMPT.format(
            goal=goal, skills_summary=skills_summary
        )
        result = await self._provider.complete(prompt)
        try:
            import json

            data = json.loads(self._extract_json(result))
            return Workflow(
                goal=goal,
                steps=[WorkflowStep(**s) for s in data.get("steps", [])],
                reasoning=data.get("reasoning", ""),
            )
        except Exception:
            return self._default_decompose(goal)

    def _default_decompose(self, goal: str) -> Workflow:
        return Workflow(
            goal=goal,
            reasoning="Default decomposition: recon -> analyze -> report",
            steps=[
                WorkflowStep(
                    id="step-1",
                    description="Reconnaissance and information gathering",
                    depends_on=[],
                ),
                WorkflowStep(
                    id="step-2",
                    description="Vulnerability analysis and assessment",
                    depends_on=["step-1"],
                ),
                WorkflowStep(
                    id="step-3",
                    description="Generate findings and recommendations",
                    depends_on=["step-2"],
                ),
            ],
        )

    def _extract_json(self, text: str) -> str:
        start = text.find("{")
        end = text.rfind("}") + 1
        if start >= 0 and end > start:
            return text[start:end]
        return "{}"
