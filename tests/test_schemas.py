from src.schemas import (
    ProductContent, ProductEntity, PricingModel,
    ResearchPaperContent, ResearchPaperEntity,
    StartupContent, StartupContentData, StartupEntity,
    JobContent, JobEntity, Source,
)


def test_startup_entity_validates_with_full_data():
    entity = StartupEntity(
        source=Source(name="YC", url="https://ycombinator.com/companies/openai"),
        content=StartupContent(entityName="OpenAI", data=StartupContentData(employeeCount=500)),
    )
    assert entity.recordType == "STARTUP"
    assert entity.schemaVersion == "1.0"
    assert entity.content.entityName == "OpenAI"
    assert entity.content.data.employeeCount == 500


def test_startup_entity_employee_count_defaults_to_none():
    entity = StartupEntity(
        source=Source(name="YC", url="https://ycombinator.com/companies/x"),
        content=StartupContent(entityName="X"),
    )
    assert entity.content.data.employeeCount is None


def test_product_entity_pricing_model_optional():
    entity = ProductEntity(
        source=Source(name="PH", url="https://producthunt.com/posts/x"),
        content=ProductContent(startupName="X"),
    )
    assert entity.content.pricingModel is None


def test_product_entity_pricing_model_enum_validates():
    entity = ProductEntity(
        source=Source(name="PH", url="https://producthunt.com/posts/x"),
        content=ProductContent(startupName="X", pricingModel=PricingModel.FREEMIUM),
    )
    assert entity.content.pricingModel == PricingModel.FREEMIUM


def test_research_paper_entity_github_fields_optional():
    entity = ResearchPaperEntity(
        source=Source(name="Arxiv", url="https://arxiv.org/abs/1234.5678"),
        content=ResearchPaperContent(
            title="A Paper", authors=["Alice"], paper_url="https://arxiv.org/abs/1234.5678"
        ),
    )
    assert entity.content.github_url is None
    assert entity.content.github_stars is None


def test_job_entity_validates():
    entity = JobEntity(
        source=Source(name="OpenAI (Ashby)", url="https://jobs.ashbyhq.com/openai/1"),
        content=JobContent(company="OpenAI", date="2026-07-19T00:00:00+00:00", is_remote=True, role_family="Engineering"),
    )
    assert entity.content.company == "OpenAI"
    assert entity.content.is_remote is True
