.PHONY: ci-schema-dump playwright-ci playwright-integration playwright-all

# Regenerate the CI schema snapshot from the live fortress_shadow database.
# Run this whenever migrations change, then commit fortress-guest-platform/ci/.
#
# Usage:
#   make ci-schema-dump
#   make ci-schema-dump DB=fortress_shadow_test
ci-schema-dump:
	bash scripts/ci-schema-dump.sh $(if $(DB),$(DB),)

# Run only the CI-safe Playwright subset (no @integration tests).
# Same as what runs on every PR via GitHub Actions.
playwright-ci:
	cd fortress-guest-platform/apps/storefront && \
	npx playwright test --grep-invert "@integration" --pass-with-no-tests

# Run only @integration tests (requires DGX cluster: NIM on spark-1, Qdrant on spark-4).
# Run this from spark-node-2 or any machine with DGX network access.
playwright-integration:
	cd fortress-guest-platform/apps/storefront && \
	npx playwright test --grep "@integration" --reporter=list

# Run ALL Playwright tests (CI-safe + @integration).
playwright-all:
	cd fortress-guest-platform/apps/storefront && \
	npx playwright test --reporter=list
