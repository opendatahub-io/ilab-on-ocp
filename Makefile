.PHONY: standalone pipeline

PYTHON_IMAGE    ?= "quay.io/modh/odh-generic-data-science-notebook@sha256:72c1d095adbda216a1f1b4b6935e3e2c717cbc58964009464ccd36c0b98312b2"      # v3-20250116
TOOLBOX_IMAGE   ?= "registry.redhat.io/ubi9/toolbox@sha256:da31dee8904a535d12689346e65e5b00d11a6179abf1fa69b548dbd755fa2770"                     # v9.5
OC_IMAGE        ?= "registry.redhat.io/openshift4/ose-cli@sha256:08bdbfae224dd39c81689ee73c183619d6b41eba7ac04f0dce7ee79f50531d0b"               # v4.15.0
RHELAI_IMAGE    ?= "registry.redhat.io/rhelai1/instructlab-nvidia-rhel9@sha256:05cfba1fb13ed54b1de4d021da2a31dd78ba7d8cc48e10c7fe372815899a18ae" # v1.3.2

# Compile Params
ILAB_PIPELINE_FILE_NAME       ?= "pipeline.yaml"
ILAB_SKIP_SDG	    	      ?= ""
ILAB_SKIP_TRAINING_PHASE_1    ?= ""
ILAB_SKIP_TRAINING_PHASE_2    ?= ""
ILAB_SKIP_EVAL_MTBENCH        ?= ""
ILAB_SKIP_EVAL_FINAL          ?= ""
ILAB_SKIP_UPLOAD_RESULT_MODEL ?= ""
ILAB_SKIP_CLEANUP_PVCS        ?= ""

standalone:
	python3 pipeline.py gen-standalone
	ruff format standalone/standalone.py

.PHONY: pipeline_all
pipeline_all: pipeline pipeline_sdgonly pipeline_dataproconly pipeline_trainonly

pipeline:
	PYTHON_IMAGE=$(PYTHON_IMAGE) \
	TOOLBOX_IMAGE=$(TOOLBOX_IMAGE) \
	OC_IMAGE=$(OC_IMAGE) \
	RHELAI_IMAGE=$(RHELAI_IMAGE) \
	python3 pipeline.py

pipeline_sdgonly:
	PYTHON_IMAGE=$(PYTHON_IMAGE) \
	TOOLBOX_IMAGE=$(TOOLBOX_IMAGE) \
	OC_IMAGE=$(OC_IMAGE) \
	RHELAI_IMAGE=$(RHELAI_IMAGE) \
	ILAB_PIPELINE_FILE_NAME="pipeline_sdgonly.yaml" \
	ILAB_SKIP_DATA_PROCESSING="True" \
	ILAB_SKIP_TRAINING_PHASE_1="True" \
	ILAB_SKIP_TRAINING_PHASE_2="True" \
	ILAB_SKIP_EVAL_MTBENCH="True" \
	ILAB_SKIP_EVAL_FINAL="True" \
	ILAB_SKIP_UPLOAD_RESULT_MODEL="True" \
	ILAB_SKIP_UPLOAD_METRICS="True" \
	python3 pipeline.py

pipeline_dataproconly:
	PYTHON_IMAGE=$(PYTHON_IMAGE) \
	TOOLBOX_IMAGE=$(TOOLBOX_IMAGE) \
	OC_IMAGE=$(OC_IMAGE) \
	RHELAI_IMAGE=$(RHELAI_IMAGE) \
	ILAB_PIPELINE_FILE_NAME="pipeline_dataproconly.yaml" \
	ILAB_SKIP_SDG="True" \
	ILAB_SKIP_TRAINING_PHASE_1="True" \
	ILAB_SKIP_TRAINING_PHASE_2="True" \
	ILAB_SKIP_EVAL_MTBENCH="True" \
	ILAB_SKIP_EVAL_FINAL="True" \
	ILAB_SKIP_UPLOAD_RESULT_MODEL="True" \
	ILAB_SKIP_UPLOAD_METRICS="True" \
	python3 pipeline.py

pipeline_trainonly:
	PYTHON_IMAGE=$(PYTHON_IMAGE) \
	TOOLBOX_IMAGE=$(TOOLBOX_IMAGE) \
	OC_IMAGE=$(OC_IMAGE) \
	RHELAI_IMAGE=$(RHELAI_IMAGE) \
	ILAB_PIPELINE_FILE_NAME="pipeline_trainonly.yaml" \
	ILAB_SKIP_SDG="True" \
	ILAB_SKIP_EVAL_MTBENCH="True" \
	ILAB_SKIP_EVAL_FINAL="True" \
	ILAB_SKIP_UPLOAD_RESULT_MODEL="True" \
	ILAB_SKIP_UPLOAD_METRICS="True" \
	python3 pipeline.py

# TODO(gfrasca): ucomment once we have implemented trainingonly
# pipeline_evalonly:
# 	PYTHON_IMAGE=$(PYTHON_IMAGE) \
# 	TOOLBOX_IMAGE=$(TOOLBOX_IMAGE) \
# 	OC_IMAGE=$(OC_IMAGE) \
# 	RHELAI_IMAGE=$(RHELAI_IMAGE) \
# 	ILAB_PIPELINE_FILE_NAME="pipeline_evalonly.yaml" \
# 	ILAB_SKIP_SDG="True" \
# 	ILAB_SKIP_TRAINING_PHASE_1="True" \
# 	ILAB_SKIP_TRAINING_PHASE_2="True" \
# 	ILAB_SKIP_UPLOAD_RESULT_MODEL="True" \
# 	python3 pipeline.py
