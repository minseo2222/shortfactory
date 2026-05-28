# Schemas

JSON schemas are generated from the Pydantic models in
`src/shorts_pipeline/models.py`.

Manual schema edits are not allowed. If a contract changes, update the Pydantic
model first, regenerate schemas in a later phase, and commit the generated
schema files with tests.
