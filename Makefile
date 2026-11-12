# PYTHONPATH=src: iCloud-synced folders can hide the editable-install file, so set the path explicitly.
RUN = PYTHONPATH=src uv run python
ENV = set -a && . ./.env && set +a &&  # API keys for the model calls

bills:
	$(RUN) -m bill_onboard.fake_bills

test:
	uv run pytest -q

.PHONY: bills test evals server worker demo

evals:
	$(ENV) $(RUN) evals/run.py

# Live demo: three terminals. 1) make server  2) make worker  3) make demo BILL=bills_hard/hb01.png
BILL ?= bills_hard/hb01.png
server:
	temporal server start-dev
worker:
	$(ENV) $(RUN) -m bill_onboard.worker
demo:
	$(RUN) -m bill_onboard.demo $(BILL)
