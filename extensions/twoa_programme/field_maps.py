"""TWoA EPCE programme Jira field aliases. Employer encoding; not portable defaults."""

from __future__ import annotations

from artifact.jira_fields import BUG_DEFECT_FIELDS, TESTLET_FIELDS


def field_aliases() -> dict[str, str]:
    """Semantic names to EPCE customfield ids for guarded test-issue writes."""

    return {
        # Story-level fields — confirmed against TWoA Jira instance (/rest/api/3/field)
        "Story": "customfield_10577",
        "Acceptance Criteria": "customfield_10377",
        "Background": "customfield_10378",
        "Solution": "customfield_11168",
        "Notes": "customfield_10475",
        "Story Points": "customfield_10026",
        "T-Shirt Size": "customfield_11234",
        # KPMG (TWOA) sync-hub traceability — holds the source KPMG issue URL
        "KPMG Reference": "customfield_15272",
        # Testlet fields
        "Test Description": TESTLET_FIELDS["test_description"],
        "Test Steps": TESTLET_FIELDS["test_steps"],
        "Expected Behaviour": TESTLET_FIELDS["expected_behaviour"],
        "Environment": TESTLET_FIELDS["environment"],
        "Functional Area": TESTLET_FIELDS["functional_area"],
        "Test Types": TESTLET_FIELDS["test_types"],
        # Bug / Buglet fields
        "Bug Description": BUG_DEFECT_FIELDS["bug_description"],
        "Actual Behaviour": BUG_DEFECT_FIELDS["actual_behaviour"],
        "Steps to Reproduce": BUG_DEFECT_FIELDS["steps_to_reproduce"],
        "Severity": BUG_DEFECT_FIELDS["severity"],
    }


def supports_hygiene() -> bool:
    return True


def default_issue_type_map() -> dict[str, list[str]]:
    """Allowed parent issue types per child (EPCE defaults)."""

    return {
        "Story": ["Epic"],
        "Testlet": ["Story"],
        "Buglet": ["Story"],
        "Bug": ["Epic"],
    }
