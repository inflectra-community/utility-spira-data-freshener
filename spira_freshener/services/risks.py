"""Risk generation and injection service for SpiraFreshener.

Generates realistic RiskRecord objects from project context and config,
and injects them into Spira via the REST API.
"""

from __future__ import annotations

import logging
import random
from datetime import datetime
from typing import TYPE_CHECKING

import requests

from spira_freshener.config import FreshenerConfig
from spira_freshener.models import InjectionResult, ProjectContext, RiskRecord

if TYPE_CHECKING:
    from spira_freshener.client import SpiraClient

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Impact and Probability ID mappings
# ---------------------------------------------------------------------------

IMPACT_IDS: dict[str, int] = {
    "Critical": 1,
    "High": 2,
    "Medium": 3,
    "Low": 4,
    "Very Low": 5,
}

PROBABILITY_IDS: dict[str, int] = {
    "Very High": 1,
    "High": 2,
    "Medium": 3,
    "Low": 4,
    "Very Low": 5,
}

# ---------------------------------------------------------------------------
# Name and description templates
# ---------------------------------------------------------------------------

_NAME_TEMPLATES = [
    "Risk: {component} may {issue}",
    "Potential {issue} in {component}",
    "{component} — {issue} risk",
]

_COMPONENTS = [
    "Authentication service",
    "Database cluster",
    "Payment gateway",
    "API gateway",
    "CI/CD pipeline",
    "Cloud storage",
    "Logging infrastructure",
    "Load balancer",
    "User session manager",
    "Third-party integration",
    "Email delivery service",
    "Search indexer",
    "Backup system",
    "Monitoring stack",
    "DNS configuration",
]

_ISSUES = [
    "become unavailable during peak load",
    "expose sensitive data",
    "fail silently",
    "exceed capacity limits",
    "lose data during failover",
    "introduce latency spikes",
    "fail to scale horizontally",
    "become a single point of failure",
    "corrupt data under concurrent writes",
    "miss SLA targets",
    "experience configuration drift",
    "be exploited via known vulnerability",
    "cause cascading failures",
    "exceed budget thresholds",
    "block release timeline",
]

_DESCRIPTION_TEMPLATES = [
    (
        "Risk identified for {component}.\n\n"
        "Scenario: {component} may {issue} under certain conditions.\n\n"
        "Potential impact: {impact}\n"
        "Mitigation: {mitigation}"
    ),
    (
        "There is a risk that {component} could {issue}.\n\n"
        "This was identified during {phase} review.\n"
        "Likelihood increases when {trigger}.\n\n"
        "Recommended action: {mitigation}"
    ),
    (
        "Summary: {component} — potential to {issue}.\n\n"
        "Context: {trigger}.\n"
        "Consequence: {impact}.\n"
        "Proposed mitigation: {mitigation}."
    ),
]

_IMPACTS = [
    "Service disruption affecting all end users",
    "Data loss or corruption requiring manual recovery",
    "Revenue loss due to downtime",
    "Compliance violation and potential audit findings",
    "Degraded user experience leading to churn",
    "Delayed delivery of planned features",
    "Reputational damage to the organisation",
]

_MITIGATIONS = [
    "Implement redundancy and automatic failover",
    "Add monitoring and alerting for early detection",
    "Conduct regular load testing",
    "Schedule periodic security audits",
    "Document and rehearse disaster recovery procedures",
    "Allocate buffer in the release timeline",
    "Introduce circuit breakers and graceful degradation",
]

_PHASES = ["architecture", "sprint planning", "security", "performance", "operational readiness"]

_TRIGGERS = [
    "traffic exceeds normal baseline by 3x",
    "a dependent service becomes unresponsive",
    "configuration changes are deployed without review",
    "the team loses a key contributor",
    "third-party API changes its contract",
    "infrastructure costs exceed projections",
    "a zero-day vulnerability is disclosed",
]


def _generate_name() -> str:
    """Generate a realistic risk name."""
    template = random.choice(_NAME_TEMPLATES)
    component = random.choice(_COMPONENTS)
    issue = random.choice(_ISSUES)
    name = template.format(component=component, issue=issue)
    return name[:255]


def _generate_description() -> str:
    """Generate a realistic risk description."""
    template = random.choice(_DESCRIPTION_TEMPLATES)
    component = random.choice(_COMPONENTS)
    issue = random.choice(_ISSUES)

    description = template.format(
        component=component,
        issue=issue,
        impact=random.choice(_IMPACTS),
        mitigation=random.choice(_MITIGATIONS),
        phase=random.choice(_PHASES),
        trigger=random.choice(_TRIGGERS),
    )
    return description[:2000]


def generate(
    context: ProjectContext,
    config: FreshenerConfig,
    now: datetime,
) -> list[RiskRecord]:
    """Generate a list of RiskRecord objects.

    Args:
        context: Project context fetched from Spira (releases, resources, etc.).
        config: FreshenerConfig controlling counts, weights, etc.
        now: The reference datetime (UTC). Currently unused but kept for API consistency.

    Returns:
        A list of exactly ``config.risks.count`` RiskRecord objects,
        or an empty list if context is missing required data.
    """
    if not context.releases:
        logger.warning(
            "No releases found in project %d — skipping Risk generation.",
            context.project_id,
        )
        return []

    if not context.resources:
        logger.warning(
            "No active resources found in project %d — skipping Risk generation.",
            context.project_id,
        )
        return []

    risk_cfg = config.risks
    count = risk_cfg.count

    # Build weighted selection lists for impact
    impact_names = list(risk_cfg.impact_weights.weights.keys())
    impact_weight_values = list(risk_cfg.impact_weights.weights.values())

    # Build weighted selection lists for probability
    prob_names = list(risk_cfg.probability_weights.weights.keys())
    prob_weight_values = list(risk_cfg.probability_weights.weights.values())

    records: list[RiskRecord] = []

    for _ in range(count):
        # Impact: weighted random
        impact_name = random.choices(impact_names, weights=impact_weight_values, k=1)[0]
        impact_id = IMPACT_IDS.get(impact_name, 3)

        # Probability: weighted random
        prob_name = random.choices(prob_names, weights=prob_weight_values, k=1)[0]
        prob_id = PROBABILITY_IDS.get(prob_name, 3)

        # Owner: uniform random from resources
        owner = random.choice(context.resources)
        owner_id = owner["UserId"]

        # Release: uniform random from releases
        release = random.choice(context.releases)
        release_id = release["ReleaseId"]

        # Name and description
        name = _generate_name()
        description = _generate_description()

        records.append(
            RiskRecord(
                name=name,
                description=description,
                risk_impact_id=impact_id,
                risk_probability_id=prob_id,
                owner_id=owner_id,
                release_id=release_id,
            )
        )

    return records


def inject(
    records: list[RiskRecord],
    client: "SpiraClient",
    project_id: int,
) -> InjectionResult:
    """POST each RiskRecord to the Spira REST API.

    Args:
        records:    The list of RiskRecord objects to inject.
        client:     A SpiraClient instance.
        project_id: The Spira project ID to inject into.

    Returns:
        An InjectionResult with created/failed counts.
    """
    created = 0
    failed = 0

    for index, record in enumerate(records):
        body = {
            "Name": record.name,
            "Description": record.description,
            "RiskStatusId": None,
            "RiskTypeId": None,
            "RiskImpactId": record.risk_impact_id,
            "RiskProbabilityId": record.risk_probability_id,
            "OwnerId": record.owner_id,
            "ReleaseId": record.release_id,
        }
        try:
            client.post(f"projects/{project_id}/risks", body)
            created += 1
        except requests.HTTPError as exc:
            status_code = getattr(getattr(exc, "response", None), "status_code", "unknown")
            logger.error(
                "Failed to inject risk (type=risk, index=%d, status=%s): %s",
                index,
                status_code,
                exc,
            )
            failed += 1

    return InjectionResult(artifact_type="risks", created=created, failed=failed)
