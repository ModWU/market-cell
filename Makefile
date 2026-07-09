.PHONY: analyze-sample cells test test-python test-rust

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
