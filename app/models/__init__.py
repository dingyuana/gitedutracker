from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Optional

from pydantic import field_validator, model_validator
from sqlmodel import SQLModel, Field
from sqlalchemy import UniqueConstraint


class StudentBase(SQLModel):
    name: str = Field(min_length=1)
    email: str = Field(min_length=1, unique=True)
    github_repo: str = Field(min_length=1)
    github_url: Optional[str] = None
    student_no: Optional[str] = None
    created_at: Optional[datetime] = Field(default_factory=lambda: datetime.now(timezone.utc))

    @field_validator('github_repo', mode='before')
    def normalize_github_repo(cls, v):
        if v is None:
            return v
        v = str(v).strip()
        if v.endswith('.git'):
            v = v[:-4]
        if v.startswith('http'):
            parts = v.rstrip('/').split('/')
            return parts[-2] + '/' + parts[-1]
        return v


class Student(StudentBase, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    github_url: Optional[str] = None
    project_id: Optional[int] = Field(default=None, foreign_key='project.id')

    @model_validator(mode='before')
    def set_github_url(cls, data):
        if isinstance(data, dict) and 'github_repo' in data:
            repo = data['github_repo']
            if isinstance(repo, str) and repo.startswith('http'):
                data = dict(data)
                data['github_url'] = repo
        return data


class Project(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    name: str = Field(min_length=1)
    description: Optional[str] = None
    start_date: Optional[date] = None
    end_date: Optional[date] = None
    status: str = Field(default='active')
    created_at: Optional[datetime] = Field(default_factory=lambda: datetime.now(timezone.utc))


class DailyPlan(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    project_id: int = Field(foreign_key='project.id')
    date: date
    content: str = Field(min_length=1)
    student_id: Optional[int] = Field(default=None, foreign_key='student.id')
    created_at: Optional[datetime] = Field(default_factory=lambda: datetime.now(timezone.utc))


class GithubActivity(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    student_id: int = Field(foreign_key='student.id')
    date: date
    commits_count: int = Field(default=0)
    commits_json: Optional[str] = None
    prs_opened: int = Field(default=0)
    prs_merged: int = Field(default=0)
    loc_additions: int = Field(default=0)
    loc_deletions: int = Field(default=0)
    status: str = Field(default='pending')
    fetched_at: Optional[datetime] = None
    saved_context_json: Optional[str] = None


class Assessment(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    student_id: int = Field(foreign_key='student.id')
    project_id: int = Field(foreign_key='project.id')
    date: date
    # 评测类型：diff=当日变更评审（默认），full=全项目综合评测
    eval_type: str = Field(default="diff", max_length=16)
    # 超出设计要求的功能加分（full 模式，0-15）
    bonus_score: Optional[float] = None
    quality_score: Optional[float] = None
    match_score: Optional[float] = None
    volume_score: Optional[float] = None
    schedule_status: str = Field(default='ontime')
    schedule_adjustment: float = Field(default=0.0)
    total_score: Optional[float] = None
    comment: Optional[str] = None
    status: str = Field(default='pending')
    attempts: int = Field(default=0)
    next_retry_at: Optional[datetime] = None
    saved_context_json: Optional[str] = None
    email_sent: bool = Field(default=False)
    created_at: Optional[datetime] = Field(default_factory=lambda: datetime.now(timezone.utc))
    evaluated_at: Optional[datetime] = None

    __table_args__ = (UniqueConstraint('student_id', 'project_id', 'date', 'eval_type'),)


class ScoringConfig(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    w_volume: float = Field(default=0.333)
    w_quality: float = Field(default=0.333)
    w_match: float = Field(default=0.333)
    loc_threshold: int = Field(default=100)
    schedule_bonus: float = Field(default=5.0)
    schedule_penalty: float = Field(default=-5.0)
    updated_at: Optional[datetime] = Field(default_factory=lambda: datetime.now(timezone.utc))


class LlmConfig(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    llm_base_url: Optional[str] = None
    llm_api_key: Optional[str] = None
    llm_model: Optional[str] = None
    llm_context_max_chars: Optional[int] = None
    updated_at: Optional[datetime] = Field(default_factory=lambda: datetime.now(timezone.utc))


class SmtpConfig(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    smtp_host: Optional[str] = None
    smtp_port: Optional[int] = None
    smtp_user: Optional[str] = None
    smtp_pass: Optional[str] = None
    smtp_from: Optional[str] = None
    updated_at: Optional[datetime] = Field(default_factory=lambda: datetime.now(timezone.utc))
