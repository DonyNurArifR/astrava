import enum

from pydantic import BaseModel, Field

from app.models.project import StudioType


class ObjectiveComplexity(enum.StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class ObjectiveUnderstandingRequest(BaseModel):
    objective: str = Field(..., min_length=3, max_length=5000)
    studio_type: StudioType | None = None
    project_id: str | None = None
    project_context: str | None = None


class ObjectiveUnderstandingResponse(BaseModel):
    objective_summary: str
    studio: StudioType
    project_context: str = ""
    intended_outcome: str
    required_capabilities: list[str] = Field(default_factory=list)
    relevant_constraints: list[str] = Field(default_factory=list)
    expected_deliverables: list[str] = Field(default_factory=list)
    complexity: ObjectiveComplexity = ObjectiveComplexity.MEDIUM
    ambiguities: list[str] = Field(default_factory=list)
    missing_information: list[str] = Field(default_factory=list)
    potential_risks: list[str] = Field(default_factory=list)
    needs_clarification: bool = False
    clarification_questions: list[str] = Field(default_factory=list)
