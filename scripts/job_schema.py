"""Pydantic models matching the data/jobs_found.json schema."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class JobListing(BaseModel):
    id: str
    title: str
    company: str
    location: str
    remote_type: Literal["remote", "hybrid", "onsite"] | None = None
    salary_min: int | None = None
    salary_max: int | None = None
    salary_type: Literal["annual", "hourly"] | None = None
    description: str = ""
    requirements: list[str] = Field(default_factory=list)
    nice_to_haves: list[str] = Field(default_factory=list)
    responsibilities: list[str] = Field(default_factory=list)
    benefits: list[str] = Field(default_factory=list)
    url: str
    source_board: str
    posted_date: str | None = None
    posted_date_estimated: bool = False
    application_deadline: str | None = None
    application_method: Literal[
        "direct_apply", "email", "external_link", "easy_apply"
    ] | None = None
    company_size: str | None = None
    industry: str | None = None
    department: str | None = None
    experience_years_min: int | None = None
    experience_years_max: int | None = None
    education_required: Literal[
        "bachelors", "masters", "phd", "none"
    ] | None = None
    employment_type: Literal[
        "full_time", "part_time", "contract", "internship"
    ] | None = None
    seniority_level: Literal[
        "intern", "entry", "mid", "senior", "lead"
    ] | None = None
    skills_mentioned: list[str] = Field(default_factory=list)
    tools_mentioned: list[str] = Field(default_factory=list)
    company_description: str | None = None
    team_info: str | None = None
    hiring_manager: str | None = None
    number_of_applicants: str | None = None
    easy_apply: bool = False
    visa_sponsorship: Literal["yes", "no", "not_mentioned"] = "not_mentioned"
    clearance_required: Literal[
        "none", "basic", "secret", "top_secret", "not_mentioned"
    ] = "not_mentioned"
    company_careers_url: str | None = None
    company_ats_platform: str | None = None
    company_direct_search_url: str | None = None
    careers_page_verified: bool = False
    found_date: str = ""
    last_seen_date: str = ""
    link_status: Literal["verified", "dead", "redirected"] | None = None
    link_dead_date: str | None = None
    raw_listing_text: str = ""


class SearchMetadata(BaseModel):
    search_date: str
    queries_used: list[str] = Field(default_factory=list)
    boards_searched: list[str] = Field(default_factory=list)
    total_found: int = 0
    new_jobs_found: int = 0
    updated_jobs: int = 0
    errors: list[str] = Field(default_factory=list)


class JobsFoundFile(BaseModel):
    metadata: SearchMetadata
    jobs: list[JobListing] = Field(default_factory=list)
