# Thin wrappers around the npm scripts (which handle Windows/POSIX venv paths).
.PHONY: setup dev test scrape
setup: ; npm run setup
dev: ; npm run dev
test: ; npm test
scrape: ; npm run scrape
