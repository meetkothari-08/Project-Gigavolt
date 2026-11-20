.PHONY: install install-ml lint test test-integration db db-raw db-validate profile audit reconcile cluster-rehearsal

install:            ## Core package + dev tools (RAG server)
	pip install -e ".[dev]"

install-ml:         ## Add embedding model, tokenizer and PDF extraction (vector server)
	pip install -e ".[dev,ml]"

lint:
	ruff check .
	shellcheck scripts/*.sh m3-ha-cluster/scripts/*.sh m3-ha-cluster/local-test/*.sh

test:               ## Offline unit tests (no databases or model servers needed)
	pytest -q

test-integration:   ## Requires a MariaDB deployed with `make db-raw` or `make db SEED=...`
	GIGAVOLT_TEST_MARIADB=1 pytest -q tests/test_integration_mariadb.py

db:                 ## Deploy schema and SQL objects; optional SEED=path/to/silver_seed.sql
	scripts/deploy_database.sh $(if $(SEED),--seed $(SEED)) --validate

db-raw:             ## Build Bronze -> Silver from the raw CSVs in RAW (default data/raw/erp)
	scripts/deploy_database.sh --raw-dir $(or $(RAW),data/raw/erp) --validate

db-validate:
	scripts/deploy_database.sh --validate

profile:            ## Data-quality profile of the raw ERP extracts
	python m1-erp-pipeline/tools/profile_raw_erp.py data/raw/erp

reconcile:          ## Compare rebuilt Silver with a reference schema: make reconcile REF=gigavolt_prod
	python m1-erp-pipeline/tools/compare_silver.py --candidate gigavolt --reference $(REF) --apply-fixes

audit:              ## Re-audit citations in the latest saved RAG benchmark
	python m6-ops-evaluation/benchmark/audit_saved_answers.py $$(ls -t m6-ops-evaluation/results/benchmark_*.csv | head -1)

cluster-rehearsal:  ## Replay every M3 procedure on a local 3-node Galera cluster (root; DUMP=gigavolt_dump.sql)
	sudo m3-ha-cluster/local-test/rehearse.sh $(DUMP)
