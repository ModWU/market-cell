.PHONY: analyze-sample cells test test-python test-rust benchmark benchmark-python

PYTHONPATH := packages/python/src

analyze-sample:
	PYTHONPATH=$(PYTHONPATH) python3 -m market_cell analyze examples/btc_usd_sample.json --pretty

cells:
	PYTHONPATH=$(PYTHONPATH) python3 -m market_cell cells --pretty

test: test-python test-rust

test-python:
	PYTHONPATH=$(PYTHONPATH) python3 -m unittest discover -s packages/python/tests

test-rust:
	cargo test

benchmark: benchmark-python

benchmark-python:
	PYTHONPATH=$(PYTHONPATH) python3 -m market_cell benchmark benchmarks/default_analysis.json --pretty
