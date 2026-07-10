PYTHON ?= python

.PHONY: install test panel-fixture fixtures clean

install:
	$(PYTHON) -m pip install -e ".[dev]"

test:
	$(PYTHON) -m pytest

panel-fixture:
	$(PYTHON) -m etf_dislocations.cli build-panel --mode fixture

fixtures:
	$(PYTHON) scripts/make_fixtures.py

clean:
	rm -rf data/panel/*.csv .pytest_cache
	find . -type d -name __pycache__ -exec rm -rf {} +
