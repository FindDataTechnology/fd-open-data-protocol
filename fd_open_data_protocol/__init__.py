"""fd-open-data-protocol: the open-data datasource protocol.

A manifest contract a datasource exposes (datasource + functions + columns +
concept hints + fetch reference) so that fd-open-data-mcp - or any consumer -
can ingest it via ``register_datasource``. Ship one manifest file -> the
datasource is added; no consumer-side wiring.
"""
__version__ = "0.1.0"
