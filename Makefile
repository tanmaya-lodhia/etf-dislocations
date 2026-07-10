PYTHON ?= python

.PHONY: install test panel-fixture run-all-fixture freeze-public fixtures clean

install:
	$(PYTHON) -m pip install -e ".[dev]"

test:
	$(PYTHON) -m pytest

panel-fixture:
	$(PYTHON) -m etf_dislocations.cli build-panel --mode fixture

run-all-fixture:
	$(PYTHON) -m etf_dislocations.cli run-all --mode fixture

freeze-public:
	$(PYTHON) -m etf_dislocations.cli freeze --mode public --price-source yahoo

fixtures:
	$(PYTHON) scripts/make_fixtures.py

clean:
	rm -rf data/panel/*.csv .pytest_cache
	find . -type d -name __pycache__ -exec rm -rf {} +
