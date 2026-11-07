# Repository agent rules

- All Git commits and all version changes in this project must be performed by a
  dedicated subagent running `openai/gpt-6-luna#high`. The primary agent may make
  other implementation, test, and documentation changes.
- Do not silently substitute another model or perform these steward-only actions
  in the primary session. If the required dedicated subagent/model is unavailable,
  stop and ask the user rather than proceeding.
- Version changes include core/addon package versions, source version constants,
  lock metadata, release tags/metadata, and versioned changelog headings. Historical
  release records must remain unchanged.
