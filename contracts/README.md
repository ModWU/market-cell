# MarketCell Contracts

This directory contains language-neutral contracts shared by all MarketCell runtimes.

Current contracts are JSON Schema files because the v0.x system exchanges structured JSON through the CLI, saved reports, and future service APIs.

Directory policy:

- `json_schema/analysis_request.schema.json`: external input accepted by the analysis runtime.
- `json_schema/analysis_report.schema.json`: stable report shape emitted by the analysis runtime.

Future language modules must depend on these contracts instead of duplicating private data shapes.
