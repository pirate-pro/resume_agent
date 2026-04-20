from collections.abc import Iterable

from sqlalchemy.orm import Session

from app.core.db.repositories.job_repository import JobRepository
from app.core.db.session import SessionLocal

DEFAULT_JOB_DATA = [
    {
        "company": "Atlas AI",
        "industry": "AI SaaS",
        "city": "Shanghai",
        "company_description": "Enterprise AI workflow platform.",
        "jobs": [
            {
                "title": "Backend Engineer",
                "city": "Shanghai",
                "education_requirement": "本科",
                "experience_min_years": 2,
                "description": "Build FastAPI services for job-matching workflows.",
                "skills": [("Python", True, 1.0), ("FastAPI", True, 1.0), ("PostgreSQL", True, 0.8), ("Docker", False, 0.5)],
            },
            {
                "title": "Machine Learning Platform Engineer",
                "city": "Shanghai",
                "education_requirement": "本科",
                "experience_min_years": 3,
                "description": "Own model serving and platform tooling.",
                "skills": [("Python", True, 1.0), ("Docker", True, 0.9), ("Kubernetes", False, 0.6), ("Redis", False, 0.4)],
            },
        ],
    },
    {
        "company": "Blue River Tech",
        "industry": "Recruitment Technology",
        "city": "Shanghai",
        "company_description": "Recruitment automation and internal tooling.",
        "jobs": [
            {
                "title": "Senior FastAPI Engineer",
                "city": "Shanghai",
                "education_requirement": "本科",
                "experience_min_years": 3,
                "description": "Deliver resume parsing, scoring and workflow APIs.",
                "skills": [("Python", True, 1.0), ("FastAPI", True, 1.0), ("SQLAlchemy", True, 0.9), ("Redis", False, 0.5)],
            },
            {
                "title": "Platform Engineer",
                "city": "Shanghai",
                "education_requirement": "本科",
                "experience_min_years": 2,
                "description": "Platform backend with Docker and PostgreSQL.",
                "skills": [("Python", True, 1.0), ("Docker", True, 0.8), ("PostgreSQL", True, 0.8), ("AWS", False, 0.5)],
            },
        ],
    },
    {
        "company": "Nebula Commerce",
        "industry": "E-commerce",
        "city": "Hangzhou",
        "company_description": "Commerce infrastructure team.",
        "jobs": [
            {
                "title": "Java Backend Engineer",
                "city": "Hangzhou",
                "education_requirement": "本科",
                "experience_min_years": 2,
                "description": "Build Java services for core commerce flows.",
                "skills": [("Java", True, 1.0), ("Spring Boot", True, 1.0), ("Redis", False, 0.5), ("MySQL", False, 0.5)],
            },
            {
                "title": "Data Platform Engineer",
                "city": "Hangzhou",
                "education_requirement": "本科",
                "experience_min_years": 3,
                "description": "Own batch and streaming data platform.",
                "skills": [("Python", True, 1.0), ("PostgreSQL", False, 0.5), ("Docker", False, 0.4), ("AWS", False, 0.5)],
            },
        ],
    },
    {
        "company": "Delta Finance",
        "industry": "FinTech",
        "city": "Shenzhen",
        "company_description": "Risk and settlement systems.",
        "jobs": [
            {
                "title": "Go Backend Engineer",
                "city": "Shenzhen",
                "education_requirement": "本科",
                "experience_min_years": 2,
                "description": "High throughput services and internal APIs.",
                "skills": [("Go", True, 1.0), ("PostgreSQL", False, 0.5), ("Docker", False, 0.4), ("Redis", False, 0.4)],
            },
            {
                "title": "Python Workflow Engineer",
                "city": "Shenzhen",
                "education_requirement": "本科",
                "experience_min_years": 2,
                "description": "Workflow tooling and document processing services.",
                "skills": [("Python", True, 1.0), ("FastAPI", False, 0.6), ("Docker", False, 0.5), ("PostgreSQL", False, 0.5)],
            },
        ],
    },
    {
        "company": "Northwind Cloud",
        "industry": "Cloud Infrastructure",
        "city": "Beijing",
        "company_description": "Internal platform and DevOps enablement.",
        "jobs": [
            {
                "title": "Cloud Platform Engineer",
                "city": "Beijing",
                "education_requirement": "本科",
                "experience_min_years": 3,
                "description": "Container platform and observability.",
                "skills": [("Docker", True, 1.0), ("Kubernetes", True, 1.0), ("Go", False, 0.4), ("Python", False, 0.4)],
            },
            {
                "title": "Internal Tools Engineer",
                "city": "Beijing",
                "education_requirement": "本科",
                "experience_min_years": 2,
                "description": "Developer productivity tools.",
                "skills": [("Python", True, 1.0), ("FastAPI", False, 0.5), ("PostgreSQL", False, 0.5), ("React", False, 0.5)],
            },
        ],
    },
    {
        "company": "Springline Health",
        "industry": "HealthTech",
        "city": "Shanghai",
        "company_description": "Patient workflow platform.",
        "jobs": [
            {
                "title": "Data Integration Engineer",
                "city": "Shanghai",
                "education_requirement": "本科",
                "experience_min_years": 2,
                "description": "Integrate clinical and workflow data.",
                "skills": [("Python", True, 1.0), ("PostgreSQL", True, 0.8), ("Docker", False, 0.5), ("Redis", False, 0.4)],
            },
            {
                "title": "Application Backend Engineer",
                "city": "Shanghai",
                "education_requirement": "本科",
                "experience_min_years": 2,
                "description": "Backend APIs for healthcare workflow products.",
                "skills": [("Python", True, 1.0), ("FastAPI", True, 0.9), ("SQLAlchemy", False, 0.5), ("Docker", False, 0.4)],
            },
        ],
    },
    {
        "company": "Lattice Games",
        "industry": "Gaming",
        "city": "Chengdu",
        "company_description": "Online game infrastructure.",
        "jobs": [
            {
                "title": "Service Engineer",
                "city": "Chengdu",
                "education_requirement": "本科",
                "experience_min_years": 2,
                "description": "Game backend services with Redis and Go.",
                "skills": [("Go", True, 1.0), ("Redis", True, 0.8), ("Docker", False, 0.5), ("PostgreSQL", False, 0.4)],
            },
            {
                "title": "Tools Engineer",
                "city": "Chengdu",
                "education_requirement": "本科",
                "experience_min_years": 2,
                "description": "Build internal tools for operations.",
                "skills": [("Python", True, 1.0), ("FastAPI", False, 0.5), ("React", False, 0.4), ("Docker", False, 0.3)],
            },
        ],
    },
    {
        "company": "Beacon Retail",
        "industry": "Retail",
        "city": "Nanjing",
        "company_description": "Omnichannel retail systems.",
        "jobs": [
            {
                "title": "Backend Developer",
                "city": "Nanjing",
                "education_requirement": "本科",
                "experience_min_years": 2,
                "description": "Retail backend services and data sync.",
                "skills": [("Python", True, 1.0), ("PostgreSQL", False, 0.5), ("Docker", False, 0.4), ("Redis", False, 0.4)],
            },
            {
                "title": "Operations Platform Engineer",
                "city": "Nanjing",
                "education_requirement": "本科",
                "experience_min_years": 2,
                "description": "Build internal workflow tools for operations.",
                "skills": [("Python", True, 1.0), ("FastAPI", False, 0.5), ("SQLAlchemy", False, 0.4), ("Docker", False, 0.4)],
            },
        ],
    },
    {
        "company": "Ocean Route Logistics",
        "industry": "Logistics",
        "city": "Guangzhou",
        "company_description": "Logistics network optimization.",
        "jobs": [
            {
                "title": "Backend Integration Engineer",
                "city": "Guangzhou",
                "education_requirement": "本科",
                "experience_min_years": 2,
                "description": "Integrate logistics systems and APIs.",
                "skills": [("Python", True, 1.0), ("PostgreSQL", False, 0.5), ("Docker", False, 0.4), ("AWS", False, 0.4)],
            },
            {
                "title": "Workflow Platform Engineer",
                "city": "Guangzhou",
                "education_requirement": "本科",
                "experience_min_years": 2,
                "description": "Internal workflow and automation platform.",
                "skills": [("Python", True, 1.0), ("FastAPI", True, 0.7), ("Redis", False, 0.4), ("Docker", False, 0.4)],
            },
        ],
    },
    {
        "company": "Quantum Ads",
        "industry": "AdTech",
        "city": "Shanghai",
        "company_description": "Ads delivery and targeting platform.",
        "jobs": [
            {
                "title": "Platform Backend Engineer",
                "city": "Shanghai",
                "education_requirement": "本科",
                "experience_min_years": 3,
                "description": "High availability backend services.",
                "skills": [("Python", True, 1.0), ("Redis", True, 0.7), ("PostgreSQL", True, 0.7), ("Docker", False, 0.5)],
            },
            {
                "title": "Data Workflow Engineer",
                "city": "Shanghai",
                "education_requirement": "本科",
                "experience_min_years": 2,
                "description": "Data and workflow systems.",
                "skills": [("Python", True, 1.0), ("SQLAlchemy", False, 0.5), ("PostgreSQL", False, 0.5), ("FastAPI", False, 0.5)],
            },
        ],
    },
]


def seed_default_jobs(db: Session | None = None) -> None:
    should_commit = db is None
    session = db or SessionLocal()
    try:
        repo = JobRepository(session)
        if repo.count_jobs() > 0:
            return
        for company_payload in DEFAULT_JOB_DATA:
            company = repo.create_company(
                company_payload["company"],
                industry=company_payload["industry"],
                city=company_payload["city"],
                description=company_payload["company_description"],
            )
            for job in company_payload["jobs"]:
                repo.create_job(
                    company.id,
                    title=job["title"],
                    city=job["city"],
                    description=job["description"],
                    education_requirement=job["education_requirement"],
                    experience_min_years=job["experience_min_years"],
                    skills=job["skills"],
                )
        if should_commit:
            session.commit()
    finally:
        if should_commit:
            session.close()


if __name__ == "__main__":
    seed_default_jobs()
