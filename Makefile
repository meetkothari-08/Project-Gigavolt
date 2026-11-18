.PHONY: install install-ml lint test test-integration db db-validate profile audit

install:            ## Core package + dev tools (RAG server)
	pip install -e ".[dev]"

install-ml:         ## Add embedding model, tokenizer and PDF extraction (vector server)
	pip install -e ".[dev,ml]"

lint:
	ruff check .

test:               ## Offline unit tests (no databases or model servers needed)
	pytest -q

test-integration:   ## Requires a MariaDB deployed with `make db SEED=...`
	GIGAVOLT_TEST_MARIADB=1 pytest -q tests/test_integration_mariadb.py

db:                 ## Deploy schema and SQL objects; optional SEED=path/to/silver_seed.sql
	sql/deploy.sh $(if $(SEED),--seed $(SEED)) --validate

db-validate:
	sql/deploy.sh --validate

profile:            ## Data-quality profile of the raw ERP extracts
	python tools/profile_raw_erp.py data/raw/erp

audit:              ## Re-audit citations in the latest saved RAG benchmark
	python benchmarks/audit_saved_answers.py $$(ls -t benchmarks/results/rag/benchmark_*.csv | head -1)
