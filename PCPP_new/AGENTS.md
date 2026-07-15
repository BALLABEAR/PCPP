# Coding Rules

- use FastAPI routers
- avoid business logic inside endpoints
- every service must be isolated
- every pipeline step is independent
- no functions longer than 50 lines
- use type hints everywhere
- every public function must contain docstring
- no hidden magic
- explicit dependencies only

# Architecture Rules

- use Clean Architecture / Hexagonal style
- use typed contracts everywhere
- define boundary interfaces before implementations
- keep domain layer framework-agnostic
- store decisions as ADR files in `docs/adr/`
- orchestrator must stay model-agnostic: no hardcoded model-specific logic, no assumptions about particular neural networks
- integration of models must go through universal contracts only
- if a file grows by responsibility or becomes hard to read, split it into focused modules
- prefer deleting obsolete code over preserving it for potential future use
- every file must have a single clear responsibility; when adding a file, document its role in `docs/repo-structure.md`

# AI Refactoring Rules

- prefer replacing broken logic over extending it
- remove dead and obsolete code immediately
- do not preserve legacy code without explicit reason
- do not introduce fallback chains and nested if-else structures
- before adding new logic, check whether existing logic can be removed
- if a function becomes difficult to understand, rewrite it instead of patching it

# AI-Friendly Conventions

- write short and explicit names for modules and functions
- keep files small and focused
- every public function and class must have a concise Russian comment in the format `# <description>` placed directly above its definition, explaining its purpose and role in the system
- never introduce implicit runtime behavior
- update `docs/architecture.md` before changing architecture

# Required Project Maps

- `docs/architecture.md` — the primary source of truth for system architecture, components, responsibilities, and interactions.
- `docs/repo-structure.md` — the canonical description of repository structure, module placement, and organizational rules.
- before any structural change, update these documents first and only then modify the code.
