.PHONY: ci-schema-dump

# Regenerate the CI schema snapshot from the live fortress_shadow database.
# Run this whenever migrations change, then commit fortress-guest-platform/ci/.
#
# Usage:
#   make ci-schema-dump
#   make ci-schema-dump DB=fortress_shadow_test
ci-schema-dump:
	bash scripts/ci-schema-dump.sh $(if $(DB),$(DB),)
