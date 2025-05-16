.PHONY: pipeline

PYTHON_IMAGE          ?= "quay.io/modh/odh-generic-data-science-notebook@sha256:72c1d095adbda216a1f1b4b6935e3e2c717cbc58964009464ccd36c0b98312b2"      # v3-20250116
TOOLBOX_IMAGE         ?= "registry.redhat.io/ubi9/toolbox@sha256:da31dee8904a535d12689346e65e5b00d11a6179abf1fa69b548dbd755fa2770"                     # v9.5
OC_IMAGE              ?= "registry.redhat.io/openshift4/ose-cli@sha256:08bdbfae224dd39c81689ee73c183619d6b41eba7ac04f0dce7ee79f50531d0b"               # v4.15.0
RHELAI_IMAGE          ?= "registry.redhat.io/rhelai1/instructlab-nvidia-rhel9@sha256:3e6eb035c69b204746a44b3a58b2751c20050cfb6af2ba7989ba327809f87c0b" # 1.5-1747182923
RUNTIME_GENERIC_IMAGE ?= "quay.io/opendatahub/ds-pipelines-runtime-generic@sha256:02445dbd6919b4a7954c34cd4625220b58985b347103454ffe3c820795a91779"    # main-bc6eba4

pipeline:
	PYTHON_IMAGE=$(PYTHON_IMAGE) \
	TOOLBOX_IMAGE=$(TOOLBOX_IMAGE) \
	OC_IMAGE=$(OC_IMAGE) \
	RHELAI_IMAGE=$(RHELAI_IMAGE) \
	RUNTIME_GENERIC_IMAGE=$(RUNTIME_GENERIC_IMAGE) \
	python3 pipeline.py
