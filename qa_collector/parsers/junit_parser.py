"""Parse JUnit XML (Playwright's `junit` reporter, pytest's --junitxml) into
qa_collector's normalized TestCase list.

Both frameworks emit standard JUnit XML, so one parser covers both -- only
tag extraction differs, since neither the JUnit schema nor Playwright/pytest
agree on where a test's tags/markers live: Playwright's `tag` option appends
each tag as a literal `@name` substring to the reported test title, whereas
pytest's default --junitxml omits markers entirely. For pytest we fall back
to inferring the marker from the test module's package path (e.g.
tests/rest/test_orders_rest.py -> 'rest'), matching backend-agentic's
convention of one tests/<marker>/ directory per pytest marker.
"""

from __future__ import annotations

import re
from xml.etree import ElementTree as ET

from qa_collector.normalize import TestCase

_TAG_RE = re.compile(r"@\w+")


def _duration_ms(time_attr: str | None) -> int | None:
    if not time_attr:
        return None
    try:
        return round(float(time_attr) * 1000)
    except ValueError:
        return None


def _pytest_marker_tag(classname: str) -> list[str]:
    parts = re.split(r"[./]", classname)
    if "tests" in parts:
        idx = parts.index("tests")
        if idx + 1 < len(parts):
            return [parts[idx + 1]]
    return []


def parse_junit_xml(xml_bytes: bytes) -> list[TestCase]:
    root = ET.fromstring(xml_bytes)
    suites = [root] if root.tag == "testsuite" else root.findall(".//testsuite")

    cases: list[TestCase] = []
    for suite in suites:
        suite_name = suite.get("name", "unknown-suite")
        for tc in suite.findall("testcase"):
            name = tc.get("name", "unknown-test")
            classname = tc.get("classname", suite_name)
            duration_ms = _duration_ms(tc.get("time"))

            status = "passed"
            error_message = None
            failure = tc.find("failure")
            error = tc.find("error")
            skipped = tc.find("skipped")
            if failure is not None:
                status = "failed"
                error_message = (failure.get("message") or failure.text or "").strip()[:4000]
            elif error is not None:
                status = "failed"
                error_message = (error.get("message") or error.text or "").strip()[:4000]
            elif skipped is not None:
                status = "skipped"

            tags = _TAG_RE.findall(f"{classname} {name}") or _pytest_marker_tag(classname)

            cases.append(
                TestCase(
                    suite=classname or suite_name,
                    test_name=name,
                    status=status,
                    tags=tags,
                    duration_ms=duration_ms,
                    error_message=error_message,
                )
            )
    return cases
