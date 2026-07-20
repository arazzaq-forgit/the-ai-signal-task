"""
Canonical entity schemas — mirrors the field tables in the assignment doc exactly.
Any record that fails validation here should be logged and dropped, never
force-coerced, so we never ship malformed or hallucinated rows.
"""
from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field, HttpUrl


SCHEMA_VERSION = "1.0"


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class Source(BaseModel):
    name: str
    url: HttpUrl


class PricingModel(str, Enum):
    FREE = "FREE"
    FREEMIUM = "FREEMIUM"
    PAID = "PAID"
    ENTERPRISE = "ENTERPRISE"


# ---------- Startup ----------

class StartupContentData(BaseModel):
    employeeCount: Optional[int] = None


class StartupContent(BaseModel):
    entityName: str
    data: StartupContentData = Field(default_factory=StartupContentData)


class StartupEntity(BaseModel):
    schemaVersion: str = SCHEMA_VERSION
    recordType: str = "STARTUP"
    source: Source
    content: StartupContent
    collectedAt: str = Field(default_factory=now_iso)


# ---------- Product ----------

class ProductContent(BaseModel):
    startupName: str
    pricingModel: Optional[PricingModel] = None


class ProductEntity(BaseModel):
    schemaVersion: str = SCHEMA_VERSION
    recordType: str = "PRODUCT"
    source: Source
    content: ProductContent
    collectedAt: str = Field(default_factory=now_iso)


# ---------- Research Paper ----------

class ResearchPaperContent(BaseModel):
    title: str
    authors: list[str] = Field(default_factory=list)
    paper_url: HttpUrl
    github_url: Optional[HttpUrl] = None
    github_stars: Optional[int] = None
    published_date: Optional[str] = None  # ISO-8601


class ResearchPaperEntity(BaseModel):
    schemaVersion: str = SCHEMA_VERSION
    recordType: str = "RESEARCH_PAPER"
    source: Source
    content: ResearchPaperContent
    collectedAt: str = Field(default_factory=now_iso)


# ---------- Job ----------

class JobContent(BaseModel):
    company: str
    date: Optional[str] = None  # ISO-8601
    is_remote: Optional[bool] = None
    role_family: Optional[str] = None


class JobEntity(BaseModel):
    schemaVersion: str = SCHEMA_VERSION
    recordType: str = "JOB"
    source: Source
    content: JobContent
    collectedAt: str = Field(default_factory=now_iso)
