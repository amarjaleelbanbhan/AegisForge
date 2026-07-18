# CortexWard — reproducibility entry point (evaluation-framework.md §8).
#
# `make reproduce` regenerates the one benchmark artifact this project ships
# today: `ward bench run/report` against `cortexward-eval`'s shipped golden
# dataset (the "novel" split — see ROADMAP.md Phase 3.5), producing a
# `RunManifest` plus a Markdown/JSON metrics report. No research paper with
# its own tables/figures exists in this repository yet to regenerate beyond
# that; this target reproduces exactly what §8 asks for out of what this
# project has actually built.

.PHONY: reproduce

GOLDEN_DATASET := packages/cortexward-eval/datasets/golden/v1/manifest.json
RESULTS_DIR := bench-results

reproduce:
	mkdir -p $(RESULTS_DIR)
	uv run ward bench run $(GOLDEN_DATASET) --output $(RESULTS_DIR)/golden-v1.json
	uv run ward bench report $(RESULTS_DIR)/golden-v1.json --format md,json \
		--output $(RESULTS_DIR)/golden-v1-report
