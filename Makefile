SHELL := /bin/bash
.DEFAULT_GOAL := help
PYTHON ?= python3
INVENTORY ?= ansible/inventory/local/hosts.yml
SITE ?= $(dir $(INVENTORY))group_vars/mb_ai.yml
LIMIT ?= mb_ai
RUN = INVENTORY="$(INVENTORY)" LIMIT="$(LIMIT)" bash scripts/ansible.sh

.PHONY: help deps validate lint test render preflight check bootstrap-zero bootstrap security-check security-apply security-verify infra-deploy deploy tls-bootstrap tls-check tls-adopt provision verify external-verify migrate migrate-verify rollback legacy-rollback runner-build runner-test
help:
	@echo 'Read-only: preflight, check, security-check, verify, external-verify'
	@echo 'Apply: bootstrap, security-apply, tls-bootstrap, tls-adopt, infra-deploy, provision, migrate'
	@echo 'Recovery: rollback RELEASE=<id>, legacy-rollback RECEIPT=<id.json>'
	@echo 'Development: deps, validate, render, runner-build, runner-test; operator interface: ./infra help'
deps:
	$(PYTHON) -m pip install -r requirements-ci.txt
	ansible-galaxy collection install -r ansible/requirements.yml
render:
	$(PYTHON) scripts/render.py --output build/tls --runtime-path /opt/mb-ai-infra/releases/test
	$(PYTHON) scripts/render.py --output build/http --runtime-path /opt/mb-ai-infra/releases/test-http --http-only
test:
	$(PYTHON) -m unittest discover -s tests -v
lint:
	yamllint .
	ansible-lint
	shellcheck infra runner/*.sh scripts/*.sh ci/*.sh ci/managed-node/*.sh ci/check-node/*.sh
validate: test render lint
	@for file in ansible/playbooks/*.yml ci/ssh-peer-context.yml; do ansible-playbook -i ansible/inventory/example/hosts.yml --syntax-check "$$file"; done
preflight:
	$(RUN) preflight
check:
	$(RUN) provision --check --diff
bootstrap-zero:
	$(RUN) bootstrap-zero
bootstrap:
	$(RUN) bootstrap
security-check security-verify:
	$(RUN) security-check
security-apply:
	$(RUN) security
infra-deploy deploy:
	$(RUN) deploy
tls-bootstrap:
	$(RUN) tls
tls-check:
	$(RUN) tls-check
tls-adopt:
	$(RUN) tls-adopt
provision:
	$(RUN) provision
verify:
	$(RUN) verify
external-verify:
	$(PYTHON) scripts/probe.py --site "$(SITE)" $(PROBE_ARGS)
migrate:
	$(RUN) migrate
migrate-verify: verify external-verify
rollback:
	@test -n "$(RELEASE)" || { echo 'Set RELEASE=<retained release id>'; exit 2; }
	$(RUN) rollback -e "infra_rollback_release=$(RELEASE)"
legacy-rollback:
	@test -n "$(RECEIPT)" || { echo 'Set RECEIPT=<migration receipt.json>'; exit 2; }
	$(RUN) legacy-rollback -e "infra_migration_receipt=$(RECEIPT)"
runner-build:
	docker build --build-arg VCS_REF="$$(git rev-parse HEAD)" -t mb-ai-infra-runner:test -f runner/Dockerfile .
runner-test: runner-build
	bash ci/runner-integration.sh mb-ai-infra-runner:test
	bash ci/runner-integration.sh mb-ai-infra-runner:test password
	@for version in 22 24; do for mode in password nopasswd; do bash ci/check-integration.sh mb-ai-infra-runner:test "$$version" "$$mode" || exit $$?; done; done
