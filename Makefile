.PHONY: clean
clean: clean-test clean-build clean-pyc clean-docs

.PHONY: clean-build
clean-build:
	rm -fr build/
	rm -fr dist/
	rm -fr .eggs/
	rm -fr pip-wheel-metadata
	find . -name '*.egg-info' -exec rm -fr {} +
	find . -name '*.egg' -exec rm -fr {} +
	find . -type d -name __pycache__ -exec rm -rv {} +
	rm -fr Pipfile.lock

.PHONY: clean-docs
clean-docs:
	rm -fr site/

.PHONY: clean-pyc
clean-pyc:
	find . -name '*.pyc' -exec rm -f {} +
	find . -name '*.pyo' -exec rm -f {} +
	find . -name '*~' -exec rm -f {} +
	find . -name '__pycache__' -exec rm -fr {} +
	find . -name '.DS_Store' -exec rm -fr {} +

.PHONY: clean-test
clean-test:
	rm -fr .tox/
	rm -f .coverage
	find . -name ".coverage*" -not -name ".coveragerc" -exec rm -fr "{}" \;
	rm -fr coverage.xml
	rm -fr htmlcov/
	rm -fr .hypothesis
	rm -fr .pytest_cache
	rm -fr .mypy_cache/
	rm -fr .hypothesis/
	find . -name 'log.txt' -exec rm -fr {} +
	find . -name 'log.*.txt' -exec rm -fr {} +

# isort: fix import orders
# black: format files according to the pep standards
.PHONY: formatters
formatters:
	tomte format-code

# black-check: check code style
# isort-check: check for import order
# flake8: wrapper around various code checks, https://flake8.pycqa.org/en/latest/user/error-codes.html
# mypy: static type checker
# pylint: code analysis for code smells and refactoring suggestions
# darglint: docstring linter
.PHONY: code-checks
code-checks:
	tomte check-code

# safety: checks dependencies for known security vulnerabilities
# bandit: security linter
.PHONY: security
security:
	tomte check-security
	gitleaks detect --report-format json --report-path leak_report

# generate latest abci docstrings
# generate latest hashes for updated packages
# update copyright headers
.PHONY: generators
generators:
	find . -empty -type d -delete  # remove empty directories to avoid wrong hashes
	tox -e abci-docstrings
	tomte format-copyright --author valory --exclude-part abci  --exclude-part http_client  --exclude-part ipfs  --exclude-part ledger  --exclude-part p2p_libp2p_client  --exclude-part gnosis_safe  --exclude-part gnosis_safe_proxy_factory  --exclude-part multisend  --exclude-part service_registry  --exclude-part acn  --exclude-part contract_api  --exclude-part http  --exclude-part ipfs  --exclude-part ledger_api --exclude-part tendermint --exclude-part abstract_abci --exclude-part abstract_round_abci --exclude-part registration_abci --exclude-part reset_pause_abci --exclude-part termination_abci --exclude-part transaction_settlement_abci --exclude-part openai --exclude-part llm --exclude-part llm --exclude-part http_server --exclude-part ceramic_read_abci --exclude-part mech --exclude-part compatibility_fallback_handler --exclude-part ceramic_write_abci --exclude-part mech_interact_abci
	# tox -e fix-doc-hashes
	autonomy packages lock

.PHONY: common-checks-1
common-checks-1:
	tomte check-copyright --author valory --exclude-part abci  --exclude-part http_client  --exclude-part ipfs  --exclude-part ledger  --exclude-part p2p_libp2p_client  --exclude-part gnosis_safe  --exclude-part gnosis_safe_proxy_factory  --exclude-part multisend  --exclude-part service_registry  --exclude-part acn  --exclude-part contract_api  --exclude-part http  --exclude-part ipfs  --exclude-part ledger_api --exclude-part tendermint --exclude-part abstract_abci --exclude-part abstract_round_abci --exclude-part registration_abci --exclude-part reset_pause_abci --exclude-part termination_abci --exclude-part transaction_settlement_abci --exclude-part openai --exclude-part llm --exclude-part llm --exclude-part http_server --exclude-part ceramic_read_abci --exclude-part mech --exclude-part compatibility_fallback_handler --exclude-part ceramic_write_abci --exclude-part mech_interact_abci
	tomte check-doc-links
	tox -p -e check-hash -e check-packages -e check-doc-hashes

.PHONY: test
test:
	pytest -rfE packages/valory/skills/proposal_voter_abci/tests -rfE packages/valory/skills/proposal_collector_abci/tests --cov=packages.valory.skills.proposal_collector_abci  --cov=packages.valory.skills.proposal_voter_abci --cov-report=xml --cov-report=term --cov-report=term-missing --cov-config=.coveragerc
	find . -name ".coverage*" -not -name ".coveragerc" -exec rm -fr "{}" \;

v := $(shell pip -V | grep virtualenvs)

.PHONY: new_env
new_env: clean
	if [ ! -z "$(which svn)" ];\
	then\
		echo "The development setup requires SVN, exit";\
		exit 1;\
	fi;\

	if [ -z "$v" ];\
	then\
		pipenv --rm;\
		pipenv --clear;\
		pipenv --python 3.10;\
		pipenv install --dev --skip-lock;\
		echo "Enter virtual environment with all development dependencies now: 'pipenv shell'.";\
	else\
		echo "In a virtual environment! Exit first: 'exit'.";\
	fi

.PHONY: fix-abci-app-specs
fix-abci-app-specs:
	export PYTHONPATH=${PYTHONPATH}:${PWD} && autonomy analyse fsm-specs --update --app-class ProposalCollectorAbciApp --package packages/valory/skills/proposal_collector_abci/ || (echo "Failed to check proposal_collector_abci abci consistency" && exit 1)
	export PYTHONPATH=${PYTHONPATH}:${PWD} && autonomy analyse fsm-specs --update --app-class ProposalVoterAbciApp --package packages/valory/skills/proposal_voter_abci/ || (echo "Failed to check proposal_voter_abci abci consistency" && exit 1)
	export PYTHONPATH=${PYTHONPATH}:${PWD} && autonomy analyse fsm-specs --update --app-class GovernatooorrAbciApp --package packages/valory/skills/governatooorr_abci/ || (echo "Failed to check governatooorr_abci abci consistency" && exit 1)

.PHONY: all-linters
all-linters:
	gitleaks detect --report-format json --report-path leak_report
	tomte check-copyright --author valory --exclude-part abci  --exclude-part http_client  --exclude-part ipfs  --exclude-part ledger  --exclude-part p2p_libp2p_client  --exclude-part gnosis_safe  --exclude-part gnosis_safe_proxy_factory  --exclude-part multisend  --exclude-part service_registry  --exclude-part acn  --exclude-part contract_api  --exclude-part http  --exclude-part ipfs  --exclude-part ledger_api --exclude-part tendermint --exclude-part abstract_abci --exclude-part abstract_round_abci --exclude-part registration_abci --exclude-part reset_pause_abci --exclude-part termination_abci --exclude-part transaction_settlement_abci --exclude-part http_server --exclude-part openai --exclude-part ceramic_read_abci --exclude-part mech --exclude-part compatibility_fallback_handler --exclude-part ceramic_write_abci --exclude-part mech_interact_abci
	tox -e bandit
	tox -e safety
	tox -e check-packages
	tox -e check-abciapp-specs
	tox -e check-hash
	tox -e spell-check
	tox -e black-check
	tox -e isort-check
	tox -e flake8
	tox -e darglint
	tox -e pylint
	tox -e mypy
