"""Schemas for 'product mode' — Crucible building a real, runnable multi-file FastAPI service.

The same verify-first seam as the function-level schemas, scaled to a product: the Architect
freezes the API contract, the (blind) Adversary writes an integration-test script that exercises
the running service, the Implementer (blind to the tests) writes the files, and the oracle is a
real container that BOOTS the service and runs the tests. All fields are strict-schema friendly
(concrete types, lists of objects — no free-form dicts).
"""

from pydantic import BaseModel

from .schemas import ExplicitDecision


class Endpoint(BaseModel):
    method: str          # GET / POST / PUT / DELETE
    path: str            # e.g. "/shorten" or "/{code}"
    behavior: str        # what it does, request/response shape, status codes


class ProductSpec(BaseModel):
    name: str
    description: str
    endpoints: list[Endpoint]
    explicit_decisions: list[ExplicitDecision]
    acceptance_criteria: list[str]


class ProductFile(BaseModel):
    path: str            # relative path, e.g. "main.py" or "storage.py"
    content: str         # full file contents


class ProductCandidate(BaseModel):
    files: list[ProductFile]
    reasoning: str


class ProductOracle(BaseModel):
    boundary_notes: list[str]   # the dangerous regions the tests attack
    integration_test: str       # a runnable python script (uses httpx vs 127.0.0.1:8000);
    #                             exits 0 on success, non-zero on any failure
