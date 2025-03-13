.PHONY: standalone pipeline

PYTHON_IMAGE          ?= "quay.io/modh/odh-generic-data-science-notebook@sha256:72c1d095adbda216a1f1b4b6935e3e2c717cbc58964009464ccd36c0b98312b2"      # v3-20250116
TOOLBOX_IMAGE         ?= "registry.redhat.io/ubi9/toolbox@sha256:da31dee8904a535d12689346e65e5b00d11a6179abf1fa69b548dbd755fa2770"                     # v9.5
OC_IMAGE              ?= "registry.redhat.io/openshift4/ose-cli@sha256:08bdbfae224dd39c81689ee73c183619d6b41eba7ac04f0dce7ee79f50531d0b"               # v4.15.0
RHELAI_IMAGE          ?= "registry.redhat.io/rhelai1/instructlab-nvidia-rhel9@sha256:c656c74338e3d59bf265e4b2fa9c01a69c8212992fa6d4511aef52a441506e68" # 1.4.1-1739870750
RUNTIME_GENERIC_IMAGE ?= "quay.io/opendatahub/ds-pipelines-runtime-generic@sha256:10fe95cd2e6b85c865249d26e99571fc9a9897a75070c02fa5dcfdb3252d3eb2"    # main-3dd8265

standalone:
	python3 pipeline.py gen-standalone
	ruff format standalone/standalone.py

pipeline:
	PYTHON_IMAGE=$(PYTHON_IMAGE) \
	TOOLBOX_IMAGE=$(TOOLBOX_IMAGE) \
	OC_IMAGE=$(OC_IMAGE) \
	RHELAI_IMAGE=$(RHELAI_IMAGE) \
	RUNTIME_GENERIC_IMAGE=$(RUNTIME_GENERIC_IMAGE) \
	python3 pipeline.py
