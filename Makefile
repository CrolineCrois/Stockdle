# Thin wrapper over the npm scripts, which do the cross-platform work.
.PHONY: setup dev api web pipeline train seed-demo reset-demo test build plot

setup:       ## create the venv, install everything, build data, train the model
	npm run setup
dev:         ## run the API (:8000) and the web app (:3000) together
	npm run dev
api:
	npm run dev:api
web:
	npm run dev:web
pipeline:    ## rebuild rounds from live sources where available
	npm run pipeline
train:       ## refit the base forecasters
	npm run train
plot:        ## render data/rounds/round_preview.png
	npm run plot
seed-demo:   ## add ~40 simulated players and ~600 drawings
	npm run seed-demo
reset-demo:  ## wipe all play data, then re-seed the demo cohort
	npm run reset-demo
test:        ## backend test suite
	npm test
build:
	npm run build
