from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field


class CreateQuestionThreadRequest(BaseModel):
    agreement_ids: list[UUID] | None = Field(default=None, max_length=100)


class QuestionRequest(BaseModel):
    question: str = Field(min_length=1, max_length=500)


class CitationResponse(BaseModel):
    anchor_id: str
    supporting_quote: str


class ClaimResponse(BaseModel):
    text: str
    citations: list[CitationResponse]


class AnswerResponse(BaseModel):
    status: str
    message: str
    claims: list[ClaimResponse]


class QuestionTurnResponse(BaseModel):
    id: UUID
    question: str
    answer: AnswerResponse
    created_at: datetime


class QuestionThreadResponse(BaseModel):
    id: UUID
    organization_id: UUID
    workspace_id: UUID
    agreement_ids: list[UUID] | None
    turns: list[QuestionTurnResponse]
